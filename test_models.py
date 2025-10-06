import requests
from datetime import datetime
import os

API_URL = "http://localhost:8099/ask"

#Consultas test
queries = {
    "consulta_1": {
        "query": "Explícame de forma detallada el Memorando número UC-FCH-2025-0053-M presente en los documentos"
    },
    "consulta_2": {
        "query": "¿Qué resoluciones se aprobaron en el mes de marzo de 2025?"
    },
    "consulta_3": {
        "query": "Resume las resoluciones relacionadas con reposición de títulos"
    },
    "consulta_4": {
        "query": "¿Qué resuelve la resolución UC-CU-RES-022-2025?"
    },
    "consulta_5":{
        "query": "¿Qué decidió el Consejo Universitario sobre la dedicación del Dr. Fernando González Calle?"
    },
    "consulta_6":{
    "query": "En qué periodo académico se aplican los cambios de dedicación aprobados en la Resolución UC-CU-RES-144-2025"
    },
    "consula_7":{
        "query": "¿Por qué NO se aceptó el recurso de impugnación interpuesto por el Msc. Pablo Isaías Lazo Pillaga?"
    }
}

#Nombre del archivo de salida
MODEL = "openai/gpt-oss-20b"
EMBED = "littlejohn-ai/bge-m3-spa-law-qa HYDE Subqueries"
MODEL = MODEL.replace("/", "_")
EMBED = EMBED.replace("/", "_")

# Carpeta de salida
output_dir = "./test_results"
os.makedirs(output_dir, exist_ok=True)  # Crea la carpeta si no existe

# Archivo de salida
OUTPUT_FILE = f"{output_dir}/test_results_{MODEL}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

#Encabezado del archivo de salida
contenido_md = "# 📄 Resultados de Consultas a la API\n\n"
contenido_md += f"**Fecha de generación:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
contenido_md += f"## Modelo: {MODEL}\n\n"
contenido_md += f"## Embeding: Embed-service {EMBED}\n\n"

# Procesar cada consulta
for nombre, payload in queries.items():
    try:
        response = requests.post(API_URL, json=payload)
        response.raise_for_status()
        data = response.json()

        # Sección de la consulta
        contenido_md += f"## 🔹 {nombre}\n\n"
        contenido_md += f"**Pregunta:** {payload['query']}\n\n"
        contenido_md += f"**Respuesta:**\n\n```\n{data.get('answer','')}\n```\n\n"

        # Evidencias
        evidencias = data.get("citations", [])
        if evidencias:
            contenido_md += "### 📑 Evidencias:\n\n"
            contenido_md += "| Resolución | Sección | Fecha | Extracto |\n"
            contenido_md += "|------------|---------|-------|----------|\n"
            for ev in evidencias:
                contenido_md += f"| {ev.get('id_reso','')} | {ev.get('seccion','')} | {ev.get('fecha','')} | {ev.get('extracto','')[:80]}... |\n"
            contenido_md += "\n"

        # Documentos usados
        usados = data.get("used_docs", [])
        if usados:
            contenido_md += "### 📂 Documentos usados:\n"
            for doc in usados:
                contenido_md += f"- {doc}\n"
            contenido_md += "\n"

        contenido_md += "---\n\n"

    except Exception as e:
        contenido_md += f"Error en {nombre}: {e}\n\n---\n\n"

# Guardar todo en un único archivo Markdown
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(contenido_md)

print(f"=====Resultados guardados en {OUTPUT_FILE}======")