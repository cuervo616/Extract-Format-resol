import fitz # PyMuPDF para trabajar con PDFs
import re # Expresiones Regulares
import json
import os
import traceback
from datetime import datetime


def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text("text") + "\n"
        doc.close()
        if not text.strip():
            return ""  # si no hay texto, devolvemos string vacío
        return text
    except Exception as e:
        print(f"No se pudo abrir o extraer texto de: {pdf_path} ({e})")
        return ""  # devolvemos vacío en lugar de None

def clean_text(text):
    # Remover bloques administrativos repetidos
    patterns = [
        r"SECRETAR[ÍI]A GENERAL.*", 
        r"Página:\s*\d+\s*de\s*\d+",
        r"Versi[oó]n.*", 
        r"Vigencia.*", 
        r"C[oó]digo.*", 
        r"Aprobado por.*"
    ]
    for pat in patterns:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)

    return text.strip()

def split_secctions(text):
    # Dividir el texto en secciones basadas en encabezados comunes
    considering_regex = re.compile(r"(CONSIDERANDO:?|Considerando:?)", re.IGNORECASE)
    resolving_regex = re.compile(r"(RESUELVE:?|Resuelve:?|RESUELVO:?|Resuelvo:?)", re.IGNORECASE)

    #Buscar posiciones de los encabezados
    cons_match = considering_regex.search(text)
    res_match = resolving_regex.search(text)

    considering = []
    resolving = []

    if cons_match and res_match:
        cons_start = cons_match.end()
        res_start = res_match.start()

        #Extraer secciones de texto
        considering_section = text[cons_start:res_start].strip()
        resolving_section = text[res_match.end():].strip()

        #Dividir en listas
        parts = [c.strip() for c in re.split(r"Que\s*", considering_section) if c.strip()]
        considering = [f"Que{c}" for c in parts]


        resolving = [r.strip() for r in re.split(r"\d+\.\s*", resolving_section) if r.strip()]
    return considering, resolving

def transform_date(date_str):
    #Transformar fechas en español al formato ISO 8601 (YYYY-MM-DD)."""
    meses = {
        "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
        "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
        "septiembre": "09", "setiembre": "09", "octubre": "10",
        "noviembre": "11", "diciembre": "12"
    }

    try:
        # Normalizar a minúsculas
        date_str = date_str.strip().lower()

        # Extraer partes con regex
        match = re.match(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", date_str, re.IGNORECASE)
        if match:
            dia, mes, anio = match.groups()
            mes_num = meses.get(mes)
            if mes_num:
                return f"{anio}-{mes_num}-{int(dia):02d}"  # formato YYYY-MM-DD

        # Si no coincide, devolvemos el original
        return date_str
    except Exception as e:
        print(f"Error al transformar fecha: {date_str} ({e})")
        return date_str



def process_resolution(pdf_path,filename):
    text = extract_text_from_pdf(pdf_path)
    if not text:  # si no hay texto, retornamos None
        return None
    
    # ----- Extrar el encabezado

    #Capturar el código de la Resolución
    id_reso_match = re.search(r"Código:\s*(\S+)", text) # Ignora los espacios en blanco iniciales y captura todo el bloque de caracteres
    if id_reso_match:
        id_reso = id_reso_match.group(1).strip()
    else:
        #Obtener el id del nombre del archivo si no se encuentra en el texto
        base_name = os.path.splitext(filename)[0]
        #Eliminar el prefijo "RESOLUCIÓN_" si existe
        id_reso = re.sub(r"(?i)^resoluci[oó]n[_\-]?", "", base_name)

    #Capturar fechas en formato textual -> 1 de enero de 2020
    date_match = re.search(r"(\d{1,2}\s+de\s+\w+\s+de\s+\d{4})",text,re.IGNORECASE)
    date = transform_date(date_match.group(1)) if date_match else None

    #Capturar número de acta
    acta_match = re.search(r"Acta:\s*(\d+)", text)
    acta = acta_match.group(1) if acta_match else None

    #Capturar tipo de Sesión
    type_session_match = re.search(r"RESOLUCIÓN SESIÓN\s+([A-ZÁÉÍÓÚÑ ]+)", text, re.IGNORECASE)
    type_session = type_session_match.group(1).title() if type_session_match else None

    # ----- Dividir secciones
    text = clean_text(text) # Limpiar el texto
    considering, resolving = split_secctions(text)
    
    # ----- Capturar quien firma
    # Buscar todas las líneas que podrían ser firmantes
    signature_matches = re.findall(r"([A-ZÁÉÍÓÚÑ][^\n]+,\s*[A-ZÁÉÍÓÚÑ ]+)", text)

    # Tomar la última coincidencia como firmante
    signature = signature_matches[-1].strip() if signature_matches else None


    # ------ Contruir JSON

    resolution_data = {
        "archivo_origen": filename,
        "id_reso": id_reso,
        "fecha": date,
        "acta": acta,
        "tipo": type_session,
        "considerando": considering,
        "resuelve": resolving,
        "firmante": signature
    }
    return resolution_data

# ----- Procesar PDF y guardar JSON
input_path = os.path.expanduser("~/Desktop/Proyecto Resoluciones/Resoluciones/2024")
output_path = os.path.expanduser("~/Desktop/Proyecto Resoluciones/Resoluciones_JSON/2024")

os.makedirs(output_path, exist_ok=True) #Crear carpetas si no existen

#Archivo log
log_path = os.path.join(output_path, "errores_resoluciones.log")
with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write("Log de errores al procesar resoluciones\n")
    log_file.write("=====================================\n\n")


for filename in os.listdir(input_path):
    if filename.lower().endswith(".pdf"):
        pdf_file_path = os.path.join(input_path, filename)
        try:
            resolution_json = process_resolution(pdf_file_path, filename)

            if not resolution_json:
                print(f"No se pudo procesar {filename}, se omite.")
                with open(log_path, "a", encoding="utf-8") as log_file:
                    log_file.write(f"No se pudo procesar {filename} (sin texto o corrupto)\n\n")
                continue  # saltar a siguiente archivo
            # Archivo JSON
            base_name = os.path.splitext(filename)[0]
            json_filename = f"{base_name}.json"
            json_path = os.path.join(output_path, json_filename)
            with open(json_path, 'w', encoding='utf-8') as json_file:
                json.dump(resolution_json, json_file, ensure_ascii=False, indent=4)
            print(f"Procesado y guardado: {json_filename}")
        except Exception as e:
            error_msg = f"Error procesando {filename}: {str(e)}\n"
            print(f"Error procesando {filename}: {e}")
            #Guardar en log
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(error_msg)
                log_file.write(traceback.format_exc() + "\n")




