# app.py — Asistente DiagnOIA (Neo4j + Ollama)
# Flujo: Usuario → Neo4j (retriever) → LLM (Ollama) → Respuesta

import re
from langchain_community.graphs import Neo4jGraph
from langchain_community.chat_models import ChatOllama

# === CONFIGURACIÓN ===
import os

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")

if not all([NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD]):
    raise RuntimeError("Faltan variables de entorno para Neo4j")

# =====================

# 1) Conexiones
graph = Neo4jGraph(url=NEO4J_URI, username=NEO4J_USER, password=NEO4J_PASSWORD)
graph.refresh_schema()
print("✅ Conectado a Neo4j")
llm = ChatOllama(base_url=OLLAMA_URL, model=OLLAMA_MODEL, temperature=0.0)
print("✅ Conectado a Ollama\n")


# 2) Retrievers (consultas Cypher) 

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
    # Usa las etiquetas de reglas: RiesgoAlto / PrioridadUrgente
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
    # Contexto según el modelo: síntomas, mediciones, factores personales
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
    # Diagnóstico según el activador de reglas en Neo4j
    q = """
    MATCH (p:FrameInstance {name:$pacId})-[:TIENE_DIAGNOSTICO]->(dx:FrameInstance)
    OPTIONAL MATCH (dx)-[:ASOCIA]->(e:FrameInstance)
    OPTIONAL MATCH (dx)-[:DETERMINA]->(det:FrameInstance)
    OPTIONAL MATCH (dx)-[:SUGIERE]->(a:FrameInstance)
    OPTIONAL MATCH (dx)-[:ES_EXPLICADO_POR]->(ex:FrameInstance)
    RETURN p.name AS Paciente,
           p.nombre AS Nombre,
           p.apellido AS Apellido,
           e.name AS Enfermedad,
           collect(DISTINCT det.name) AS Detalles,
           collect(DISTINCT a.name) AS Accion,
           head(collect(DISTINCT ex.Texto)) AS Explicacion
    """
    return graph.query(q, {"pacId": pac_id})


def buscar_pacientes_por_nombre_o_apellido(texto: str):
    """
    Busca pacientes cuyo nombre, apellido o nombre completo aparezca en el texto.
    Devuelve una lista de filas con las mismas claves que q_listar_pacientes().
    """
    low = texto.lower()
    rows = q_listar_pacientes()
    coincidencias = []

    for r in rows:
        nombre = (r.get("Nombre") or "").lower()
        apellido = (r.get("Apellido") or "").lower()
        full = (nombre + " " + apellido).strip()

        if (
            (nombre and nombre in low)
            or (apellido and apellido in low)
            or (full and full in low)
        ):
            coincidencias.append(r)

    return coincidencias


# 3) Flujo principal (pregunta → retriever → LLM)

def responder(pregunta: str) -> str:
    text = pregunta.strip()
    low = text.lower()

    # 3.0 - Pregunta genérica "nombre y apellido de los pacientes"
    if "nombre" in low and "apellido" in low and "paciente" in low and "pacientes" in low:
        rows = q_listar_pacientes()
        if not rows:
            return "No hay pacientes registrados."
        lista = "; ".join(
            f"{r['Paciente']}: {r['Nombre']} {r['Apellido']}"
            for r in rows
        )
        prompt = (
            "Te doy una lista de pacientes con su identificador y nombre completo.\n"
            f"Lista: {lista}\n\n"
            "Redactá en una o dos oraciones, en español, los nombres y apellidos de todos los pacientes, "
            "mencionando su identificador entre paréntesis. No agregues código ni ejemplos técnicos."
        )
        return llm.invoke(prompt).content

    # 3.1 - Pacientes nuevos
    if any(
        k in low
        for k in [
            "pacientes nuevos",
            "nuevos pacientes",
            "últimos pacientes",
            "ultimos pacientes",
            "más recientes",
            "mas recientes",
        ]
    ):
        rows = q_pacientes_nuevos()
        if not rows:
            return "No hay pacientes en la base."

        lista = "; ".join(
            f"{r['Paciente']} - {r['Nombre']} {r['Apellido']}"
            for r in rows
        )
        prompt = (
            "Te doy una lista de pacientes más recientes, con su identificador y nombre completo.\n"
            f"Lista: {lista}\n\n"
            "Redactá en una o dos oraciones, en español, un resumen breve indicando cuántos pacientes hay "
            "y nombrándolos. No agregues código ni nada técnico."
        )
        return llm.invoke(prompt).content

    # 3.2 - Listar todos los pacientes
    if any(
        k in low
        for k in [
            "listar pacientes",
            "listame",
            "lista de pacientes",
            "todos los pacientes",
        ]
    ):
        rows = q_listar_pacientes()
        if not rows:
            return "No hay pacientes registrados."

        lista = "; ".join(
            f"{r['Paciente']} - {r['Nombre']} {r['Apellido']}"
            for r in rows
        )
        prompt = (
            "Te doy una lista de pacientes con su identificador y nombre completo.\n"
            f"Lista: {lista}\n\n"
            "Redactá en una o dos oraciones, en español, un resumen breve indicando cuántos pacientes hay "
            "y listando sus nombres completos. No escribas código ni ejemplos técnicos."
        )
        return llm.invoke(prompt).content

    # 3.3 - Pacientes que necesitan atención (usa RIESGO y PRIORIDAD del DX)
    if any(
        k in low
        for k in [
            "necesitan atención",
            "necesitan atencion",
            "atención médica",
            "atencion medica",
            "prioridad urgente",
            "riesgo alto",
        ]
    ):
        rows = q_pacientes_necesitan_atencion()
        if not rows:
            return "No hay pacientes con prioridad urgente o riesgo alto."

        partes = []
        for r in rows:
            pac = r.get("Paciente", "Paciente sin ID")
            motivos = r.get("Motivos", [])
            if motivos:
                motivos_str = ", ".join(motivos)
                partes.append(f"{pac} ({motivos_str})")
            else:
                partes.append(f"{pac} (motivo no especificado)")

        lista = "; ".join(partes)
        prompt = (
            "Te doy una lista de pacientes que requieren atención y los motivos (PrioridadUrgente, RiesgoAlto).\n"
            f"Lista: {lista}\n\n"
            "Redactá en una o dos oraciones, en español, qué pacientes requieren atención y por qué. "
            "No agregues código ni explicaciones técnicas, solo texto clínico sencillo."
        )
        return llm.invoke(prompt).content

    # 3.4 - Buscar por paciente (ID o nombre/apellido)
    m = re.search(r"(PAC[_\-]?\w+)", text, re.IGNORECASE)
    pac = m.group(1) if m else None

    if not pac:
        # Intentar identificar al paciente por nombre y/o apellido
        candidatos = buscar_pacientes_por_nombre_o_apellido(text)
        if not candidatos:
            return (
                "No reconocí un ID de paciente ni encontré coincidencias por nombre o apellido. "
                "Indicá un ID (ej.: PAC_004) o usá el nombre/apellido tal como figura en la lista de pacientes."
            )

        if len(candidatos) > 1:
            lista = "; ".join(
                f"{c['Paciente']} - {c['Nombre']} {c['Apellido']}"
                for c in candidatos
            )
            return (
                "Encontré más de un paciente que coincide con lo que escribiste: "
                f"{lista}. Por favor indicá el ID del paciente (por ejemplo: PAC_004)."
            )

        # Coincidencia única: usamos ese ID
        elegido = candidatos[0]
        pac = elegido["Paciente"]

    # 3.5 - Contexto o diagnóstico según intención
    # "síntomas" -> contexto
    # "enfermedad / diagnóstico / riesgo / prioridad / acción" -> diagnóstico
    tiene_contexto = any(
        k in low
        for k in [
            "sintoma",
            "síntoma",
            "sintomas",
            "síntomas",
            "contexto",
        ]
    )
    tiene_dx = any(
        k in low
        for k in [
            "diagn",
            "riesgo",
            "prioridad",
            "acción",
            "accion",
            "enfermedad",
            "patologia",
            "patología",
        ]
    )

    # Si pide explícitamente síntomas, vamos por contexto;
    # si pide enfermedad/riesgo/acción, vamos por diagnóstico.
    usa_dx = tiene_dx and not tiene_contexto

    rows = q_dx(pac) if usa_dx else q_contexto(pac)

    if not rows:
        todos = q_listar_pacientes()
        paciente_row = next((r for r in todos if r.get("Paciente") == pac), None)
        if paciente_row:
            nombre = paciente_row.get("Nombre", "")
            apellido = paciente_row.get("Apellido", "")
            if usa_dx:
                return (
                    f"El paciente {pac} ({nombre} {apellido}) está registrado, "
                    "pero aún no hay diagnóstico preliminar cargado en Neo4j."
                )
            else:
                return (
                    f"El paciente {pac} ({nombre} {apellido}) está registrado, "
                    "pero no hay síntomas, mediciones ni factores personales cargados en Neo4j."
                )
        else:
            return "No hay datos en Neo4j para ese paciente."

    # 3.6 - Construcción de prompt según ruta elegida

    if usa_dx:
        # Diagnóstico: Enfermedad + Riesgo + Prioridad + Acción + Explicación
        resumenes = []
        for row in rows:
            pac_id = row.get("Paciente", pac)
            nombre = row.get("Nombre") or ""
            apellido = row.get("Apellido") or ""
            enf = row.get("Enfermedad") or "enfermedad no especificada"
            detalles = row.get("Detalles") or []
            acciones = row.get("Accion") or []
            explicacion = row.get("Explicacion") or ""

            det_str = ", ".join(detalles) if detalles else "sin detalles adicionales"
            acc_str = ", ".join(acciones) if acciones else "sin acciones recomendadas"

            etiqueta_paciente = (nombre + " " + apellido).strip() or pac_id

            resumenes.append(
                f"Paciente {etiqueta_paciente} (ID {pac_id}): enfermedad = {enf}; "
                f"detalles = {det_str}; acciones sugeridas = {acc_str}; "
                f"explicación del sistema = {explicacion}."
            )

        contexto = " ".join(resumenes)

        prompt = (
            "Sos un asistente clínico. A partir de la siguiente información sobre el diagnóstico preliminar "
            "de un paciente, respondé de forma breve en español.\n"
            "Mencioná claramente:\n"
            "- la enfermedad principal,\n"
            "- el nivel de riesgo y la prioridad de atención (si aparecen en los detalles),\n"
            "- y la(s) acción(es) recomendadas.\n"
            "Podés usar la explicación generada por el sistema como apoyo, pero no repitas literalmente todo. "
            "No expliques formatos de datos ni temas técnicos, solo la situación clínica.\n\n"
            f"Datos del diagnóstico:\n{contexto}\n\n"
            f"Pregunta del usuario: '{text}'\n"
            "Respuesta breve en español:"
        )
    else:
        # Contexto: síntomas + mediciones + factores personales
        resumenes = []
        for row in rows:
            pac_id = row.get("Paciente", pac)
            sintomas = row.get("Sintomas") or []
            mediciones = row.get("Mediciones") or []
            factores = row.get("Factores") or []

            s_str = ", ".join(sintomas) if sintomas else "sin síntomas registrados"
            m_str = ", ".join(mediciones) if mediciones else "sin mediciones registradas"
            f_str = ", ".join(factores) if factores else "sin factores personales registrados"

            resumenes.append(
                f"Paciente {pac_id}: síntomas = {s_str}; mediciones = {m_str}; "
                f"factores personales = {f_str}."
            )

        contexto = " ".join(resumenes)

        prompt = (
            "Sos un asistente clínico. A partir de la siguiente información sobre un paciente, "
            "resumí en una o dos oraciones, en español, cuáles son sus síntomas, mediciones relevantes "
            "y factores personales. No expliques formatos de datos ni temas técnicos, solo la situación clínica.\n\n"
            f"Datos del paciente:\n{contexto}\n\n"
            f"Pregunta del usuario: '{text}'\n"
            "Respuesta breve en español:"
        )

    return llm.invoke(prompt).content


# 4) CLI
def main():
    print("=== Asistente DiagnOIA (Neo4j + Ollama) ===")
    print("Preguntas ejemplo:")
    print("- Listar pacientes")
    print("- ¿Qué pacientes necesitan atención?")
    print("- Mostrame los pacientes nuevos")
    print("- Mostrame los síntomas del paciente PAC_004")
    print("- Qué enfermedad tiene PAC_004")
    print("- Qué riesgo y prioridad tiene PAC_004\n")

    while True:
        try:
            q = input("> ").strip()
            if not q:
                continue
            if q.lower() in ("/salir", "salir", "exit", "/exit"):
                print("Chau!")
                break
            print(responder(q), "\n")
        except KeyboardInterrupt:
            print("\nChau!")
            break


if __name__ == "__main__":
    main()
