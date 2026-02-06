# DiagnoIA – Sistema Clínico Inteligente (Proyecto Académico)

 **Proyecto académico grupal** desarrollado como parte del Proyecto Integrador de la materia Inteligencia Artificial de la carrera Ingeniería en Sistemas.

Este repositorio se publica con fines de **portfolio personal**, con el objetivo de documentar y mostrar mi aporte técnico en el desarrollo del sistema.

---

##  Descripción

DiagnoIA es un **asistente clínico inteligente** orientado a la evaluación preliminar de pacientes, combinando:

- una base de conocimiento clínica modelada como **grafo semántico en Neo4j**,
- un **motor de reglas clínicas con scoring acumulado**,
- una interfaz de consulta en lenguaje natural,
- y un **modelo de lenguaje local (LLM)** para generar respuestas clínicas claras.

El sistema permite analizar síntomas, estimar riesgo y prioridad de atención, y sugerir acciones clínicas preliminares.

---

## Arquitectura general

El sistema está compuesto por los siguientes módulos:

- **Base de conocimiento (Neo4j)**  
  Modelada mediante:
  - FrameClass  
  - FrameInstance  
  - Slot  
  - Measurement  
  - SLOT_VALUE  

  Representa pacientes, síntomas, factores personales, diagnósticos y reglas clínicas.

- **Motor de reglas clínicas**  
  Evalúa múltiples condiciones (síntomas, mediciones y factores personales) utilizando pesos y score acumulado para:
  - sugerir enfermedad,
  - estimar nivel de riesgo,
  - definir prioridad de atención,
  - recomendar acciones.

- **Modelo de lenguaje local (Ollama)**  
  Utilizado para interpretar preguntas en lenguaje natural y generar respuestas clínicas no técnicas.  
  El modelo corre de forma local, sin enviar datos sensibles a servicios externos.

- **Interfaz de usuario (CLI / Streamlit)**  
  Permite consultar pacientes, síntomas y diagnósticos, y visualizar prioridades clínicas.

---

##  Funcionalidades principales

- Consulta de pacientes mediante lenguaje natural.
- Listado de pacientes nuevos.
- Identificación de pacientes con riesgo alto o prioridad urgente.
- Consulta de síntomas, mediciones y factores personales.
- Diagnóstico preliminar con:
  - enfermedad sugerida,
  - nivel de riesgo,
  - prioridad de atención,
  - acciones recomendadas.
- Ordenamiento de pacientes por prioridad clínica.

---

## Tecnologías utilizadas

- Python  
- Neo4j AuraDB  
- Cypher  
- LangChain (community)  
- Ollama (LLM local – llama3.2:3b)  
- Streamlit  

---

##  Rol y aporte personal

- Diseño del modelo clínico en Neo4j.
- Implementación del motor de reglas clínicas.
- Integración con LangChain y modelo de lenguaje local.
- Desarrollo de la lógica de consulta y razonamiento clínico.
- Diseño del flujo conversacional del asistente clínico.

---

##  Nota

Este sistema **no reemplaza el diagnóstico médico profesional**.  
Se trata de un proyecto académico orientado a la experimentación y al aprendizaje.

---

## Autor

Gonzalo Van Megroot
