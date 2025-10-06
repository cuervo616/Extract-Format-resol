from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any
import json
import re
from datetime import datetime
from openai import OpenAI

#Util
# Calcular el año actual y las fechas de inicio y fin del año
anio_actual = datetime.now().year
fecha_inicio = f"{anio_actual}-01-01"
fecha_fin = f"{anio_actual}-12-31"

SYSTEM_ROLE = SYSTEM_ROLE = (
    "====== INSTRUCCIONES ======"
    "Eres un asistente experto en el análisis de documentos legales de un consejo universitario."
    "Tu tarea es transformar la pregunta del usuario en un objeto JSON estructurado que servirá como filtro para consultar en una base de datos."
    
    "### 1. ANÁLISIS DE LA PREGUNTA"
    "- Identifica:"
    "  - Fechas o rangos de tiempo (exactos o relativos)."
    "  - Temas o conceptos principales."
    "  - Personas o entidades mencionadas."
    "  - Números de resolución, artículos u otros identificadores legales."
    "  - Tipo de sesión (ordinaria o extraordinaria)."
    "  - Estado de proceso (aceptado, negado, archivado, pendiente, etc.)."
    "  - Intención principal del usuario (resumir, listar, explicar_motivo, buscar_especifico)."

    "### 2. MANEJO DE FECHAS"
    "- Si se menciona un mes y año (ej: 'marzo de 2025'), calcula el rango completo:"
    "  - inicio: '2025-03-01'"
    "  - fin: '2025-03-31'"
    "- Si se mencionan términos relativos como:"
    "  - 'hoy' → usar fecha actual."
    "  - 'ayer' → fecha actual - 1 día."
    "  - 'último mes' → mes anterior completo."
    "  - 'esta semana' → lunes a domingo de la semana actual."
    f"- Si no hay ninguna fecha, coloca 'rango_fechas' como el inicio y fin del año en curso:"
    f"  'rango_fechas': {{"
    f"      'fecha_inicio': '{fecha_inicio}',"
    f"      'fecha_fin': '{fecha_fin}'"
    "  }}"

    "### 3. NORMALIZACIÓN DE TEXTO"
    "- Convierte **temas**, **nombres de personas**, y **entidades** a minúsculas para consistencia."
    "- Mantén números de resoluciones y artículos tal cual."

    "### 4. GENERACIÓN DEL JSON"
    "- Devuelve únicamente un objeto JSON válido, sin comentarios ni texto extra."
    "- No apliques saltos ni caracteres especiales, necesto el formato JSON estricto"
    "- Siempre incluye todos los campos, en el mismo orden, con null donde no encunetres nada, no uses None."

    "====== FORMATO DE SALIDA ======"
    "IMPORTANTE: Usar null, para cuando no se encuentra, no use None"
    "{"
    "  'id_resol': "
    "  'rango_fechas': {"
    "      'fecha_inicio': 'YYYY-MM-DD',"
    "      'fecha_fin': 'YYYY-MM-DD'"
    "  } OR null,"
    "  'temas_principales': [],"
    "  'nombres_involucrados': [],"
    "  'numeros_referencia': {"
    "      'id_resolucion': '',"
    "      'articulos': []"
    "  } OR null,"
    "  'tipo_session': '',"
    "  'estado_proceso': '',"
    "  'intencion_usuario': ''"
    "}"

    "====== EJEMPLOS DE PREGUNTAS Y RESPUESTAS ======"

    "Usuario: '¿Qué resoluciones se aprobaron en el mes de marzo de 2025?'"
    "Respuesta:"
    "{"
    "  'rango_fechas': {"
    "      'fecha_inicio': '2025-03-01',"
    "      'fecha_fin': '2025-03-31'"
    "  },"
    "  'temas_principales': null,"
    "  'nombres_involucrados': null,"
    "  'numeros_referencia': null,"
    "  'tipo_session': null,"
    "  'estado_proceso': null,"
    "  'intencion_usuario': 'listar'"
    "}"

    "Usuario: 'Explícame por qué se negó la reposición de título de Msc. Pablo Isaías Lazo Pillaga.'"
    "Respuesta:"
    "{"
    "   'id_resol': null"
    f"  'rango_fechas': {{'fecha_inicio': '{fecha_inicio}', 'fecha_fin': '{fecha_fin}'}},"
    "  'temas_principales': ['reposición de títulos'],"
    "  'nombres_involucrados': ['msc. pablo isaías lazo pillaga'],"
    "  'numeros_referencia': null,"
    "  'tipo_session': null,"
    "  'estado_proceso': 'negado',"
    "  'intencion_usuario': 'explicar_motivo'"
    "}"

    "Usuario: 'Dame un resumen de la sesión extraordinaria de ayer.'"
    "Respuesta:"
    "{"
    "   'id_resol': null"
    f"  'rango_fechas': {{'fecha_inicio': '{fecha_inicio}', 'fecha_fin': '{fecha_fin}'}},"
    "  'temas_principales': null,"
    "  'nombres_involucrados': null,"
    "  'numeros_referencia': null,"
    "  'tipo_session': 'extraordinaria',"
    "  'estado_proceso': null,"
    "  'intencion_usuario': 'resumir'"
    "}"

    "Usuario: '¿En qué artículos se basó la resolución UC-CU-RES-022-2025?'"
    "Respuesta:"
    "{"
    "   'id_resol': 'UC-CU-RES-022-2025'"
    f"  'rango_fechas': {{'fecha_inicio': '{fecha_inicio}', 'fecha_fin': '{fecha_fin}'}},"
    "  'temas_principales': null,"
    "  'nombres_involucrados': null,"
    "  'numeros_referencia': {"
    "      'id_resolucion': '123-2024',"
    "      'articulos': []"
    "  },"
    "  'tipo_session': null,"
    "  'estado_proceso': null,"
    "  'intencion_usuario': 'buscar_especifico'"
    "}"

    "Usuario: 'Listar las resoluciones de impugnación tratadas el último mes.'"
    "Respuesta:"
    "{"
    "   'id_resol': null"
    f"  'rango_fechas': {{'fecha_inicio': '{fecha_inicio}', 'fecha_fin': '{fecha_fin}'}},"
    "  'temas_principales': ['impugnación'],"
    "  'nombres_involucrados': null,"
    "  'numeros_referencia': null,"
    "  'tipo_session': null,"
    "  'estado_proceso': null,"
    "  'intencion_usuario': 'listar'"
    "}"
)

#Settings 
client = OpenAI(base_url="http://127.0.0.1:1234/v1",api_key="not-needed")
app = FastAPI(
    title="Query-Filter",
    description="promt detect filter",
    version="1.0.0"
)

class PromtRequest(BaseModel):
    promt: str
    max_tokens: int = 1000 

#end-point
@app.post("/query-filters")
async def query_filters(request: PromtRequest):
    """
    Recibe un promt y devuelve los filtros que ayudan a buscar mejor
    """
    try:
        completion = client.chat.completions.create(
            model= "google/gemma-3-4b",
            messages=[
                {"role": "system", "content": f"{SYSTEM_ROLE}"},
                {"role": "user", "content": request.promt}
            ],
            temperature=0.7,
            max_tokens=request.max_tokens,
        )
        raw_response = completion.choices[0].message.content.strip()

        #Buscar JSON con regex
        match = re.search(r"\{[\s\S]*\}", raw_response)
        if match:
            try:
                response_json = json.loads(match.group(0))
            except json.JSONDecodeError:
                response_json = {"error": "No se pudo parsear el JSON"}
        else:
            response_json = {"error": "No se encontró un objeto JSON"}
        print(raw_response)
        return raw_response
        return response_json
    except Exception as e:
        return {"error": f"No se pudo conectar con LM Studio. Asegúrate de que el servidor esté activo. Detalle: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = 8020
    uvicorn.run("main:app", host="0.0.0.0", port=port,reload=True)