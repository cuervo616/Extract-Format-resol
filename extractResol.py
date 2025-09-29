import os
import re
import csv
import hashlib
import time
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

# ---------------- Config ----------------
BASE_URL = "https://www.ucuenca.edu.ec/resoluciones-consejo-universitario/#"
BASE_FOLDER = os.path.expanduser("~/Desktop/Proyecto Resoluciones/Resoluciones")
ALLOWED_YEARS = {"2021", "2022", "2023", "2024", "2025"}
PER_FILE_LOG_NAME = "descargas.txt"
MASTER_LOG_CSV = os.path.join(BASE_FOLDER, "master_log.csv")
REQUEST_TIMEOUT = (10, 60)  # connect, read
SLEEP_BETWEEN = 0.4  # antidesborde, educado con el servidor
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ResolutionsDownloader/1.0; +https://example.org)"
}
# ----------------------------------------

os.makedirs(BASE_FOLDER, exist_ok=True)

def ensure_year_folder(year: str) -> str:
    """Crea y retorna la ruta de la carpeta del año (si el año es válido)."""
    if year not in ALLOWED_YEARS:
        # Si el año no está permitido, colócalo en 'otros' para revisar manualmente
        year = "otros"
    path = os.path.join(BASE_FOLDER, year)
    os.makedirs(path, exist_ok=True)
    return path

def normalize_filename(name: str) -> str:
    """Normaliza nombres para filesystem y elimina 'download' final."""
    name = name.strip()

    # Quitar 'download' (con o sin .pdf, mayúsculas/minúsculas)
    name = re.sub(r'(download\.pdf|download)$', '', name, flags=re.IGNORECASE)

    # Reemplazar separadores y caracteres raros
    name = name.replace("/", "-").replace("\\", "-").replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9._\-áéíóúÁÉÍÓÚñÑ]", "_", name)

    # Asegurar que termine en .pdf
    if not name.lower().endswith(".pdf"):
        name += ".pdf"

    return name


def pick_filename_from_headers(resp, fallback_name: str) -> str:
    """Si el servidor envía Content-Disposition, úsalo; si no, usa fallback."""
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m:
        guessed = m.group(1)
        return normalize_filename(guessed)
    return normalize_filename(fallback_name)

def extract_year(text: str) -> str | None:
    """Extrae un año 20xx desde texto/URL."""
    m = re.search(r"(20\d{2})", text)
    return m.group(1) if m else None

def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def resolve_duplicate_path(folder: str, filename: str) -> str:
    """Si filename existe en folder, genera un sufijo (_2), (_3), ... evitando sobrescribir."""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(folder, filename)
    i = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{base}({i}){ext}")
        i += 1
    return candidate

def write_master_log_row(row: dict, write_header_if_needed=True):
    header = [
        "timestamp", "source_section_year", "target_year", "url",
        "final_filename", "saved_path", "status", "reason",
        "size_bytes", "sha256"
    ]
    exists = os.path.exists(MASTER_LOG_CSV)
    with open(MASTER_LOG_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header_if_needed and not exists:
            w.writeheader()
        w.writerow(row)

def download_pdf(file_url: str, dest_folder: str, candidate_name: str) -> tuple[str, str, int]:
    """
    Descarga el PDF a dest_folder con nombre candidate_name (puede cambiar por Content-Disposition).
    Devuelve (saved_path, sha256, size).
    """
    with requests.get(file_url, stream=True, timeout=REQUEST_TIMEOUT, headers=HEADERS) as r:
        r.raise_for_status()
        # Decide filename final (puede venir de headers)
        final_name = pick_filename_from_headers(r, candidate_name)
        save_path = os.path.join(dest_folder, final_name)

        total_size = int(r.headers.get("content-length", 0))
        block = 1024 * 64
        progress = tqdm(
            total=total_size if total_size > 0 else None,
            unit="iB",
            unit_scale=True,
            desc=final_name,
            leave=False,
        )

        # Descarga a un temporal para poder calcular hash antes de renombrar por colisiones
        tmp_path = save_path + ".part"
        with open(tmp_path, "wb") as f:
            for chunk in r.iter_content(block):
                if chunk:
                    f.write(chunk)
                    progress.update(len(chunk))
        progress.close()

        # Si ya existe un archivo con el mismo nombre, compara hash. Si es igual, elimina temp y salta.
        if os.path.exists(save_path):
            old_hash = sha256_of_file(save_path)
            new_hash = sha256_of_file(tmp_path)
            if old_hash == new_hash:
                os.remove(tmp_path)
                return save_path, old_hash, os.path.getsize(save_path)
            else:
                # Diferente contenido con mismo nombre: crear ruta alternativa
                save_path = resolve_duplicate_path(dest_folder, final_name)

        # Mover el .part a definitivo
        os.replace(tmp_path, save_path)
        return save_path, sha256_of_file(save_path), os.path.getsize(save_path)

def parse_page():
    resp = requests.get(BASE_URL, timeout=REQUEST_TIMEOUT, headers=HEADERS)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def iter_year_sections(soup):
    """
    Itera por secciones de año: toma cada <h2> que contenga un año y
    recorre sus hermanos hasta el siguiente <h2>.
    """
    headers = soup.find_all("h2")
    for h in headers:
        header_text = h.get_text(strip=True)
        sec_year = extract_year(header_text)
        if not sec_year:
            continue
        # Recolectar <a> hasta el próximo h2
        links = []
        for sib in h.next_siblings:
            if getattr(sib, "name", None) == "h2":
                break
            if getattr(sib, "find_all", None):
                for a in sib.find_all("a", href=True):
                    links.append(a)
        yield sec_year, links

def main():
    soup = parse_page()

    # Preparar master log si no existe
    if not os.path.exists(MASTER_LOG_CSV):
        write_master_log_row({}, write_header_if_needed=True)  # crea encabezado
        os.remove(MASTER_LOG_CSV)  # remove fila vacía
        # crear de nuevo ya con encabezado real en la primera escritura

    for section_year, links in iter_year_sections(soup):
        year_folder = ensure_year_folder(section_year)
        per_log_path = os.path.join(year_folder, PER_FILE_LOG_NAME)

        print(f"\nProcesando sección {section_year} ({len(links)} enlaces)")

        with open(per_log_path, "a", encoding="utf-8") as perlog:
            for a in links:
                href = a["href"].strip()
                text = a.get_text(strip=True) or href

                # Filtrar solo PDFs / resoluciones
                if not (".pdf" in href.lower() or "resolución" in text.lower() or "res-" in text.lower()):
                    continue

                file_url = urljoin(BASE_URL, href)
                # Nombre candidato (basado en texto o basename de la URL)
                url_basename = os.path.basename(urlparse(file_url).path) or "documento.pdf"
                candidate_name = normalize_filename(text if len(text) > 5 else url_basename)

                # Detectar año real: prioriza año en texto, luego en URL, finalmente sección
                real_year = extract_year(text) or extract_year(file_url) or section_year
                target_folder = ensure_year_folder(real_year)

                # Ruta tentativa (para saber si ya existe antes de descargar)
                tentative_path = os.path.join(target_folder, candidate_name)
                if os.path.exists(tentative_path):
                    # Ya existe; registramos y seguimos
                    perlog.write(f"SKIP (exists) - {candidate_name}\n")
                    write_master_log_row({
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source_section_year": section_year,
                        "target_year": real_year,
                        "url": file_url,
                        "final_filename": candidate_name,
                        "saved_path": tentative_path,
                        "status": "SKIP_EXISTS",
                        "reason": "same_name_present",
                        "size_bytes": os.path.getsize(tentative_path),
                        "sha256": sha256_of_file(tentative_path)
                    }, write_header_if_needed=not os.path.exists(MASTER_LOG_CSV))
                    continue

                try:
                    saved_path, file_hash, size = download_pdf(file_url, target_folder, candidate_name)
                    perlog.write(f"OK - {os.path.basename(saved_path)}\n")
                    print(f"Descargado en {real_year}: {os.path.basename(saved_path)}")

                    write_master_log_row({
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source_section_year": section_year,
                        "target_year": real_year,
                        "url": file_url,
                        "final_filename": os.path.basename(saved_path),
                        "saved_path": saved_path,
                        "status": "OK",
                        "reason": "",
                        "size_bytes": size,
                        "sha256": file_hash
                    }, write_header_if_needed=not os.path.exists(MASTER_LOG_CSV))

                except requests.HTTPError as e:
                    msg = f"HTTP {e.response.status_code} {str(e)}"
                    perlog.write(f"ERROR - {candidate_name} - {msg}\n")
                    write_master_log_row({
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source_section_year": section_year,
                        "target_year": real_year,
                        "url": file_url,
                        "final_filename": candidate_name,
                        "saved_path": "",
                        "status": "ERROR",
                        "reason": msg,
                        "size_bytes": 0,
                        "sha256": ""
                    }, write_header_if_needed=not os.path.exists(MASTER_LOG_CSV))

                except Exception as e:
                    perlog.write(f"ERROR - {candidate_name} - {e}\n")
                    write_master_log_row({
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "source_section_year": section_year,
                        "target_year": real_year,
                        "url": file_url,
                        "final_filename": candidate_name,
                        "saved_path": "",
                        "status": "ERROR",
                        "reason": str(e),
                        "size_bytes": 0,
                        "sha256": ""
                    }, write_header_if_needed=not os.path.exists(MASTER_LOG_CSV))

                time.sleep(SLEEP_BETWEEN)  # cortesía al servidor

if __name__ == "__main__":
    main()
