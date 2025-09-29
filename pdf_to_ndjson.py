# pdf_to_json.py — NDJSON por chunk (1 línea = 1 párrafo/ítem)
import fitz  # PyMuPDF
import re
import json
import os
import traceback
import hashlib
from datetime import datetime

CHUNK_CHAR_LIMIT = 1000  # ~700–1000 recomendado

HEADER_FOOTER_PATTERNS = [
    r"SECRETAR[ÍI]A GENERAL.*",
    r"^Página:\s*\d+\s*de\s*\d+\s*$",
    r"^Versi[oó]n:?.*$",
    r"^Vigencia.*$",
    r"^C[oó]digo:\s*UC[- ]?CU[- ]?RES[- ]?\S+.*$",
    r"^Aprobado por:.*$",
    r"^Elaborado por:.*$",
    r"^PRO\s*CESO\s*DE\s*GESTI[ÓO]N\s*DE\s*SECRETAR[ÍI]A\s*DEL\s*CU.*$",
    r"^RESO\s*LUCI[ÓO]N\s*SESI[ÓO]N\s*ORDINAR[ÍI]A.*$",
    r"^Acta:\s*\d+\s*$",
    r"^\d{4}-\d{2}-\d{2}.*$"
]

CONSIDERANDO_RE = re.compile(r"\bCONSIDERANDO:?\b", re.IGNORECASE)
RESUELVE_RE = re.compile(r"\bRESUEL(VE|VO):?\b", re.IGNORECASE)
ID_RESO_RE = re.compile(r"C[oó]digo:\s*([A-Z0-9\-]+)", re.IGNORECASE)
ACTA_RE = re.compile(r"Acta:\s*(\d+)", re.IGNORECASE)
TIPO_RE = re.compile(r"RESOLUCI[ÓO]N\s+SESI[ÓO]N\s+([A-ZÁÉÍÓÚÑ ]+)", re.IGNORECASE)
FECHA_TXT_RE = re.compile(r"(\d{1,2}\s+de\s+[a-záéíóú]+?\s+de\s+\d{4})", re.IGNORECASE)
ENUM_ITEM_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)

MESES = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04", "mayo": "05",
    "junio": "06", "julio": "07", "agosto": "08", "septiembre": "09",
    "setiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12"
}

def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def normalize_spaces(s: str) -> str:
    # dehyphenation: palabra- \n continuacion -> palabra continuacion
    s = re.sub(r"(\w)-\n(\w)", r"\1\2", s)
    # saltos de línea a espacios suaves donde corresponde
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()

def tiny_ocr_fixes(s: str) -> str:
    s = s.replace("Queel", "Que el").replace("Quese", "Que se")
    return s

def clean_page_text(txt: str) -> str:
    lines = [ln for ln in txt.splitlines()]
    out = []
    for ln in lines:
        skip = False
        for pat in HEADER_FOOTER_PATTERNS:
            if re.search(pat, ln, flags=re.IGNORECASE):
                skip = True
                break
        if not skip:
            out.append(ln)
    cleaned = "\n".join(out)
    cleaned = normalize_spaces(cleaned)
    cleaned = tiny_ocr_fixes(cleaned)
    return cleaned

def extract_pages(pdf_path: str):
    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        t = page.get_text("text")
        pages.append((i+1, t))  # 1-index
    doc.close()
    return pages

def guess_id_from_filename(filename: str) -> str:
    base = os.path.splitext(filename)[0]
    # quitar prefijo “Resolución_” / “RESOLUCIÓN_”
    base = re.sub(r"(?i)^resoluci[oó]n[_\-]?", "", base)
    return base

#fecha en formato YYYY-MM-DD
def to_iso(date_txt: str) -> str | None:
    if not date_txt:
        return None
    s = date_txt.strip().lower()
    m = re.match(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", s, re.IGNORECASE)
    if not m:
        return None
    d, mon, y = m.groups()
    mon = MESES.get(mon, None)
    if not mon:
        return None
    return f"{y}-{mon}-{int(d):02d}"

def normalize_tipo(raw: str | None) -> str | None:
    if not raw:
        return None
    x = re.sub(r"\s+", " ", raw.strip()).lower()
    x = x.replace("ó", "o").replace("í", "i").strip()
    if "ordinaria" in x:
        return "Ordinaria"
    if "extraordinaria" in x:
        return "Extraordinaria"
    return raw.title()

def split_sections(full_text: str):
    # hallar offsets de encabezados
    cons = CONSIDERANDO_RE.search(full_text)
    resv = RESUELVE_RE.search(full_text)
    considering_text, resolving_text = "", ""
    if cons and resv and cons.start() < resv.start():
        considering_text = full_text[cons.end():resv.start()].strip()
        resolving_text = full_text[resv.end():].strip()
    elif resv:
        resolving_text = full_text[resv.end():].strip()
    elif cons:
        considering_text = full_text[cons.end():].strip()

    # CONSIDERANDO: separar por líneas que comienzan con "Que"
    considering_parts = []
    if considering_text:
        # normalizar "Que," y variantes pegadas
        considering_text = re.sub(r"\bQue\s*,?\s*", "Que, ", considering_text)
        parts = re.split(r"(?:\n|^)\s*Que,\s*", considering_text)
        # re.split deja el primer trozo antes del primer "Que,"; limpiamos
        for p in parts:
            p = p.strip()
            if not p:
                continue
            # vuelve a anteponer "Que, "
            considering_parts.append("Que, " + p)

    # RESUELVE: dividir por enumeración 1./2./3.
    resolving_parts = []
    if resolving_text:
        items = ENUM_ITEM_RE.split(resolving_text)
        # ENUM_ITEM_RE split devuelve primer elemento antes del 1.; descartarlo si es ruido
        # reconstruimos detectando líneas que realmente eran ítems
        # alternativa más simple: usar finditer y slices
        matches = list(ENUM_ITEM_RE.finditer(resolving_text))
        if matches:
            # tomar cada bloque desde match[i].end() a match[i+1].start()
            for i, m in enumerate(matches):
                start = m.end()
                end = matches[i+1].start() if i+1 < len(matches) else len(resolving_text)
                chunk = resolving_text[start:end].strip()
                if chunk:
                    resolving_parts.append(chunk)
        else:
            # sin numeración, dejar un único ítem
            resolving_parts = [resolving_text.strip()]

    return considering_parts, resolving_parts

def best_effort_pages_map(pages_cleaned: list[str], snippet: str) -> tuple[int|None, int|None]:
    """
    Busca un fragmento corto en las páginas para asignar pagina_inicio/fin (heurística).
    """
    if not snippet:
        return None, None
    key = snippet[:80]  # primeros 80 chars
    key = re.sub(r"\s+", " ", key).strip()
    hit_page = None
    for i, txt in enumerate(pages_cleaned, start=1):
        hay = re.sub(r"\s+", " ", txt)
        if key and key in hay:
            hit_page = i
            break
    if hit_page is None:
        return None, None
    return hit_page, hit_page

def chunk_long(text: str, limit: int = CHUNK_CHAR_LIMIT):
    if len(text) <= limit:
        return [text]
    out = []
    i = 0
    while i < len(text):
        out.append(text[i:i+limit].strip())
        i += limit
    return out

def process_pdf_to_ndjson(pdf_path: str, out_path: str):
    filename = os.path.basename(pdf_path)
    pages_raw = extract_pages(pdf_path)

    # Limpieza por página y unión
    pages_clean = []
    for pg, txt in pages_raw:
        pages_clean.append(clean_page_text(txt))
    full_text = "\n".join(pages_clean).strip()

    # Encabezado
    id_reso = None
    m = ID_RESO_RE.search("\n".join([p for _, p in pages_raw]))
    if m:
        id_reso = m.group(1).strip()
    else:
        id_reso = guess_id_from_filename(filename)

    acta = None
    m = ACTA_RE.search("\n".join([p for _, p in pages_raw]))
    if m:
        acta = m.group(1).strip()

    tipo = None
    m = TIPO_RE.search("\n".join([p for _, p in pages_raw]))
    if m:
        tipo = normalize_tipo(m.group(1))

    # fecha legible (primera que aparezca) y derivar ISO + año
    fecha_txt = None
    m = FECHA_TXT_RE.search("\n".join([p for _, p in pages_raw]))
    if m:
        fecha_txt = m.group(1)
    fecha_iso = to_iso(fecha_txt) if fecha_txt else None
    anio = int(fecha_iso[:4]) if fecha_iso else None

    # Secciones
    considering_parts, resolving_parts = split_sections(full_text)

    # Preparar NDJSON
    with open(out_path, "w", encoding="utf-8") as fw:
        # CONSIDERANDO
        for pi, ptxt in enumerate(considering_parts):
            ptxt = ptxt.strip()
            if not ptxt or len(ptxt) < 30:
                continue
            # cortar si es muy largo (manteniendo parrafo_index y variando chunk_index)
            chunks = chunk_long(ptxt, CHUNK_CHAR_LIMIT)
            for ci, ctxt in enumerate(chunks):
                p_ini, p_fin = best_effort_pages_map(pages_clean, ctxt)
                obj = {
                    "id_reso": id_reso,
                    "acta": acta,
                    "anio": anio,
                    "fecha_iso": fecha_iso,
                    "fecha": fecha_txt,
                    "seccion": "considerando",
                    "parrafo_index": pi,
                    "pagina_inicio": p_ini,
                    "pagina_fin": p_fin,
                    "texto": ctxt,
                    "fuente_pdf": filename,
                    "sha1": sha1(ctxt)
                }
                fw.write(json.dumps(obj, ensure_ascii=False) + "\n")

        # RESUELVE
        for pi, ptxt in enumerate(resolving_parts):
            ptxt = ptxt.strip()
            if not ptxt or len(ptxt) < 10:
                continue
            chunks = chunk_long(ptxt, CHUNK_CHAR_LIMIT)
            for ci, ctxt in enumerate(chunks):
                p_ini, p_fin = best_effort_pages_map(pages_clean, ctxt)
                obj = {
                    "id_reso": id_reso,
                    "acta": acta,
                    "anio": anio,
                    "fecha_iso": fecha_iso,
                    "fecha": fecha_txt,
                    "seccion": "resuelve",
                    "parrafo_index": pi,
                    "pagina_inicio": p_ini,
                    "pagina_fin": p_fin,
                    "texto": ctxt,
                    "fuente_pdf": filename,
                    "sha1": sha1(ctxt)
                }
                fw.write(json.dumps(obj, ensure_ascii=False) + "\n")

def process_folder_to_ndjson(input_dir: str, output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "errores_resoluciones.log")
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("Log de errores al procesar resoluciones\n")
        log.write("=====================================\n\n")

    for filename in sorted(os.listdir(input_dir)):
        if not filename.lower().endswith(".pdf"):
            continue
        in_pdf = os.path.join(input_dir, filename)
        base = os.path.splitext(filename)[0]
        out_ndjson = os.path.join(output_dir, f"{base}.ndjson")
        try:
            process_pdf_to_ndjson(in_pdf, out_ndjson)
            print(f"OK: {filename} -> {os.path.basename(out_ndjson)}")
        except Exception as e:
            print(f"ERROR: {filename}: {e}")
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"Error procesando {filename}: {e}\n")
                log.write(traceback.format_exc() + "\n")


if __name__ == "__main__":
    input_path = os.path.expanduser("~/Desktop/Proyecto Resoluciones/Resoluciones/2025")
    output_path = os.path.expanduser("~/Desktop/Proyecto Resoluciones/Resoluciones_NDJSON/2025")
    process_folder_to_ndjson(input_path, output_path)
