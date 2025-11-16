import streamlit as st
import re
from langchain_community.graphs import Neo4jGraph
from langchain_community.chat_models import ChatOllama

# =====================
# CONFIGURACIÓN
# =====================
NEO4J_URI = "neo4j+s://4d237a1f.databases.neo4j.io"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "anA8t6UbVakpXHq28uvWp4H4HfTkx3QYLnk8XYAOs4M"

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:3b"   # modelo liviano

graph = Neo4jGraph(url=NEO4J_URI, username=NEO4J_USER, password=NEO4J_PASSWORD)
llm = ChatOllama(base_url=OLLAMA_URL, model=OLLAMA_MODEL, temperature=0.0)


# =====================
# QUERIES A NEO4J
# =====================

def q_listar_pacientes():
    q = """
    MATCH (p:FrameInstance)-[:INSTANCE_OF]->(:FrameClass {name:'Paciente'})
    RETURN p.name AS Paciente, p.nombre AS Nombre, p.apellido AS Apellido
    ORDER BY p.name
    """
    return graph.query(q)


def q_pacientes_nuevos():
    q = """
    MATCH (p:FrameInstance)-[:INSTANCE_OF]->(:FrameClass {name:'Paciente'})
    RETURN p.name AS Paciente, p.nombre AS Nombre, p.apellido AS Apellido
    ORDER BY p.name DESC
    LIMIT 5
    """
    return graph.query(q)


def q_pacientes_necesitan_atencion():
    q = """
    MATCH (p:FrameInstance)-[:TIENE_DIAGNOSTICO]->(dx:FrameInstance)
    OPTIONAL MATCH (dx)-[:DETERMINA]->(det:FrameInstance)
    WITH p, collect(DISTINCT det.name) AS dets
    WITH p, [x IN dets WHERE x IN ['PrioridadUrgente','RiesgoAlto']] AS flags
    WHERE size(flags) > 0
    RETURN p.name AS Paciente, flags AS Motivos
    ORDER BY p.name
    """
    return graph.query(q)


def q_contexto(pac_id: str):
    q = """
    MATCH (p:FrameInstance {name:$pacId})
    OPTIONAL MATCH (p)-[:PRESENTA]->(sym:FrameInstance)
    OPTIONAL MATCH (p)-[:HAS_MEASUREMENT]->(m:Measurement)-[:OF_SLOT]->(slot:Slot)
    OPTIONAL MATCH (p)-[:TIENE]->(fp:FrameInstance)-[:INSTANCE_OF]->(:FrameClass {name:'FactoresPersonales'})
    OPTIONAL MATCH (fp)-[sv:SLOT_VALUE]->(s:Slot)
    RETURN p.name AS Paciente,
           collect(DISTINCT sym.name) AS Sintomas,
           collect(DISTINCT slot.name + '=' + toString(m.value)) AS Mediciones,
           collect(DISTINCT s.name + '=' + toString(sv.value)) AS Factores;
    """
    return graph.query(q, {"pacId": pac_id})


def q_dx(pac_id: str):
    q = """
    MATCH (p:FrameInstance {name:$pacId})-[:TIENE_DIAGNOSTICO]->(dx:FrameInstance)
    OPTIONAL MATCH (dx)-[:ASOCIA]->(e:FrameInstance)
    OPTIONAL MATCH (dx)-[:DETERMINA]->(det:FrameInstance)
    OPTIONAL MATCH (dx)-[:SUGIERE]->(acc:FrameInstance)
    OPTIONAL MATCH (dx)-[:ES_EXPLICADO_POR]->(ex:FrameInstance)
    RETURN p.name AS Paciente,
           e.name AS Enfermedad,
           collect(DISTINCT det.name) AS Detalles,
           collect(DISTINCT acc.name) AS Accion,
           head(collect(DISTINCT ex.Texto)) AS Explicacion
    """
    return graph.query(q, {"pacId": pac_id})


def buscar_pacientes_por_nombre_o_apellido(texto: str):
    low = texto.lower()
    rows = q_listar_pacientes()
    coincidencias = []

    for r in rows:
        nombre = (r.get("Nombre") or "").lower()
        apellido = (r.get("Apellido") or "").lower()
        full = (nombre + " " + apellido).strip()

        if (
            (nombre and nombre in low) or
            (apellido and apellido in low) or
            (full and full in low)
        ):
            coincidencias.append(r)

    return coincidencias


# =====================
# ORDEN POR PRIORIDAD
# =====================

def obtener_pacientes_prioridad():
    q = """
    MATCH (p:FrameInstance)-[:INSTANCE_OF]->(:FrameClass {name:'Paciente'})
    OPTIONAL MATCH (p)-[:TIENE_DIAGNOSTICO]->(dx:FrameInstance)
    OPTIONAL MATCH (dx)-[:ASOCIA]->(enf:FrameInstance)
    OPTIONAL MATCH (dx)-[:DETERMINA]->(det:FrameInstance)
    OPTIONAL MATCH (dx)-[:SUGIERE]->(acc:FrameInstance)
    RETURN p.name AS Paciente,
           p.nombre AS Nombre,
           p.apellido AS Apellido,
           enf.name AS Enfermedad,
           collect(DISTINCT det.name) AS Detalles,
           acc.name AS Accion
    """
    rows = graph.query(q)

    prioridad_map = {
        "PrioridadUrgente": 1,
        "PrioridadModerada": 2,
        "PrioridadBaja": 3,
    }

    for r in rows:
        dets = r.get("Detalles") or []
        prios = [d for d in dets if d in prioridad_map]
        r["Prioridad"] = prios[0] if prios else "Sin diagnóstico"
        r["OrdenInterno"] = prioridad_map.get(r["Prioridad"], 99)

    rows = sorted(rows, key=lambda x: x["OrdenInterno"])

    for i, r in enumerate(rows, start=1):
        r["Orden"] = i
        r.pop("OrdenInterno", None)

    return rows


# =====================
#   LÓGICA DEL CHAT
# =====================

def responder(pregunta: str) -> str:
    text = pregunta.strip()
    low = text.lower()

    # Listar pacientes
    if any(k in low for k in ["listar pacientes", "lista de pacientes", "todos los pacientes"]):
        rows = q_listar_pacientes()
        if not rows:
            return "No hay pacientes registrados en la base."
        lineas = [
            f"{r['Paciente']}: {r['Nombre']} {r['Apellido']}"
            for r in rows
        ]
        return "Pacientes registrados:\n" + "\n".join(lineas)

    # Pacientes nuevos
    if any(k in low for k in ["pacientes nuevos", "nuevos pacientes", "últimos pacientes", "ultimos pacientes"]):
        rows = q_pacientes_nuevos()
        if not rows:
            return "No hay pacientes en la base."
        lineas = [
            f"{r['Paciente']}: {r['Nombre']} {r['Apellido']}"
            for r in rows
        ]
        return "Pacientes más recientes:\n" + "\n".join(lineas)

    # Pacientes que necesitan atención
    if any(k in low for k in ["necesitan atención", "necesitan atencion", "atención médica", "atencion medica", "prioridad urgente", "riesgo alto"]):
        rows = q_pacientes_necesitan_atencion()
        if not rows:
            return "No hay pacientes con prioridad urgente o riesgo alto."
        lineas = []
        for r in rows:
            motivos = r.get("Motivos") or []
            motivos_str = ", ".join(motivos) if motivos else "motivo no especificado"
            lineas.append(f"{r['Paciente']} ({motivos_str})")
        return "Pacientes que requieren atención prioritaria:\n" + "\n".join(lineas)

    # Consultas por paciente (ID o nombre)

    m = re.search(r"(PAC[_\-]?\w+)", text, re.IGNORECASE)
    pac = m.group(1) if m else None

    if not pac:
        candidatos = buscar_pacientes_por_nombre_o_apellido(text)
        if not candidatos:
            return (
                "No reconocí un ID de paciente ni encontré coincidencias por nombre o apellido.\n\n"
                "Podés probar con:\n"
                "- \"Listar pacientes\"\n"
                "- \"Pacientes nuevos\"\n"
                "- \"Qué pacientes necesitan atención\"\n"
                "- \"Qué síntomas tiene el paciente PAC_004\" o usando el nombre tal como figura en la lista."
            )

        if len(candidatos) > 1:
            lista = "\n".join(
                f"{c['Paciente']}: {c['Nombre']} {c['Apellido']}"
                for c in candidatos
            )
            return (
                "Encontré más de un paciente que coincide con lo que escribiste:\n"
                f"{lista}\n\nIndicá el ID del paciente (por ejemplo: PAC_004)."
            )

        elegido = candidatos[0]
        pac = elegido["Paciente"]

    pide_dx = any(k in low for k in ["diagn", "riesgo", "prioridad", "enfermedad", "acción", "accion"])
    if pide_dx:
        rows = q_dx(pac)
        if not rows:
            return (
                f"El paciente {pac} está registrado, pero no tiene diagnóstico preliminar cargado en Neo4j.\n"
                "Primero deberías ejecutar el activador de reglas para ese paciente."
            )

        r = rows[0]
        enf = r.get("Enfermedad") or "No especificada"
        detalles = r.get("Detalles") or []
        acciones = r.get("Accion") or []
        exp = r.get("Explicacion") or ""

        det_str = ", ".join(detalles) if detalles else "Sin detalles adicionales"
        acc_str = ", ".join(acciones) if acciones else "Sin acción recomendada"

        return (
            f"Diagnóstico para {pac}:\n"
            f"- Enfermedad principal: {enf}\n"
            f"- Detalles (incluye riesgo y prioridad si aparecen): {det_str}\n"
            f"- Acción sugerida: {acc_str}\n"
            f"- Explicación del sistema: {exp}"
        )

    rows = q_contexto(pac)
    if not rows:
        return (
            f"El paciente {pac} está registrado, pero no tiene síntomas, mediciones ni factores personales cargados en Neo4j."
        )

    r = rows[0]
    sintomas = r.get("Sintomas") or []
    mediciones = r.get("Mediciones") or []
    factores = r.get("Factores") or []

    s_str = ", ".join(sintomas) if sintomas else "Sin síntomas registrados"
    m_str = ", ".join(mediciones) if mediciones else "Sin mediciones registradas"
    f_str = ", ".join(factores) if factores else "Sin factores personales registrados"

    return (
        f"Contexto clínico para {pac}:\n"
        f"- Síntomas: {s_str}\n"
        f"- Mediciones: {m_str}\n"
        f"- Factores personales: {f_str}"
    )


# =====================
#      STREAMLIT UI
# =====================

st.set_page_config(page_title="DiagnOIA", layout="wide")
st.title("DiagnOIA – Sistema Clínico Inteligente")

tab1, tab2 = st.tabs(["⚠️ Prioridad", "💬 Chat"])

# Tab 1: Pacientes por prioridad
with tab1:
    st.subheader("Pacientes ordenados por prioridad clínica")
    pacientes = obtener_pacientes_prioridad()
    st.dataframe(pacientes, use_container_width=True)

# Tab 2: Chat
with tab2:
    st.subheader("Chat con el asistente clínico")

    if "mensajes" not in st.session_state:
        st.session_state.mensajes = []

    pregunta = st.text_input(
        "Escribí tu pregunta:",
        placeholder="Ejemplo: Listar pacientes / ¿Qué síntomas tiene Gonzalo Van Megroot?"
    )

    if st.button("Enviar"):
        if pregunta.strip():
            respuesta = responder(pregunta)
            st.session_state.mensajes.append({"user": pregunta, "bot": respuesta})

    for m in st.session_state.mensajes:
        st.markdown(f"**Usuario:** {m['user']}")
        st.markdown("**DiagnOIA:**")
        st.write(m['bot'])
        st.markdown("---")