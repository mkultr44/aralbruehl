#!/usr/bin/env python3
import os, io, re, time, csv, json, requests, numpy as np
from urllib.parse import urljoin, urlparse
from lxml import etree
from PIL import Image, ImageOps, ImageFilter
import easyocr
from dotenv import load_dotenv

load_dotenv()

SRC_DAV = os.environ.get("SOURCE_DAV_URL","").strip().rstrip("/")
SRC_USER = os.environ.get("SOURCE_USER","").strip()
SRC_PASS = os.environ.get("SOURCE_PASS","").strip()
OUT_FILE = os.environ.get("OUTPUT_FILENAME","hermes_directory.csv")
OUTPUT_SUB = os.environ.get("OUTPUT_SUBFOLDER","output")
INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS","30"))
STATE_FILE = os.environ.get("STATE_FILE","/opt/hermes-ocr/.state.json")

AUTH = (SRC_USER, SRC_PASS)
EXTS = (".jpg",".jpeg",".png",".heic",".heif",".webp",".bmp",".tif",".tiff")
BASE = f"{urlparse(SRC_DAV).scheme}://{urlparse(SRC_DAV).netloc}"

# === EasyOCR Initialisierung ===
print("[INFO] Initializing EasyOCR...")
reader = easyocr.Reader(['de', 'en'], gpu=False, workers=os.cpu_count())
print("[INFO] EasyOCR ready.")

# === DAV-Listing ===
def propfind(url):
    headers = {"Depth": "1"}
    body = """<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop><d:getcontenttype/><d:getetag/></d:prop>
</d:propfind>"""
    r = requests.request("PROPFIND", url, data=body, headers=headers, auth=AUTH, timeout=30)
    r.raise_for_status()
    return etree.fromstring(r.content)

def list_images():
    ns = {"d":"DAV:"}
    root = propfind(SRC_DAV + "/")
    files = []
    for resp in root.findall("d:response", ns):
        href = resp.findtext("d:href", namespaces=ns)
        if not href or href.endswith("/"):
            continue
        ctype = resp.findtext(".//d:getcontenttype", namespaces=ns) or ""
        if ctype.lower().startswith("image/") or href.lower().endswith(EXTS):
            files.append(href)
    return files

def download_image(href):
    url = urljoin(BASE, href)
    r = requests.get(url, auth=AUTH, timeout=60, headers={"Accept": "*/*"})
    r.raise_for_status()
    data = r.content
    if data.startswith(b"<!") or b"<html" in data[:200].lower():
        raise RuntimeError(f"received HTML instead of image for {href}")
    return data

# === Vorverarbeitung ===
def preprocess(img):
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.MedianFilter(size=1))
    g = g.point(lambda p: 255 if p > 150 else 0)
    g = g.resize((int(g.width * 2.2), int(g.height * 2.2)))
    return g

# === EasyOCR-Auswertung ===
def ocr_text(img):
    np_img = np.array(img)
    result = reader.readtext(np_img, detail=0, paragraph=False)
    return "\n".join(result)

# === Hermes-spezifische Extraktion ===
def extract_pairs(text):
    lines = [re.sub(r'[^A-Za-z0-9,äöüÄÖÜß\s/]', '', l).strip() for l in text.splitlines() if l.strip()]
    pairs = []
    current_sn = None

    for i, line in enumerate(lines):
        m = re.search(r'[Hh7][0-9/]{6,}', line.replace(" ", ""))
        if m:
            sn = re.sub(r'[^0-9Hh]', '', m.group(0))
            if i + 1 < len(lines) and re.match(r'^\d{4,}$', lines[i + 1].replace(" ", "")):
                sn += lines[i + 1].replace(" ", "")
            current_sn = sn
            continue

        if current_sn and ("," in line or re.search(r"[A-ZÄÖÜ][a-zäöüß]+\s*[A-ZÄÖÜ][a-zäöüß]*", line)):
            name = line.strip()
            pairs.append((current_sn, name))
            current_sn = None

    return pairs

# === CSV auf Nextcloud schreiben ===
def upload_csv(mapping):
    csv_buf = io.StringIO()
    w = csv.writer(csv_buf)
    w.writerow(["sendungsnummer", "name"])
    for k in sorted(mapping.keys()):
        w.writerow([k, mapping[k]])
    data = csv_buf.getvalue().encode("utf-8")
    out_url = f"{SRC_DAV}/{OUTPUT_SUB}/{OUT_FILE}"
    r = requests.put(out_url, data=data, auth=AUTH,
                     headers={"Content-Type": "text/csv"}, timeout=60)
    print(f"[UPLOAD] {r.status_code} -> {out_url}")

# === Hauptprozess ===
def main():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"seen": {}, "map": {}}

    seen, mapping = state["seen"], state["map"]

    while True:
        try:
            print("[INFO] Checking for new files…")
            files = list_images()
            new = [f for f in files if f not in seen]
            if new:
                print(f"[INFO] {len(new)} new image(s) found")
                for href in new:
                    try:
                        data = download_image(href)
                        if len(data) < 2048:
                            raise ValueError(f"suspect small payload ({len(data)} bytes)")
                        img = preprocess(Image.open(io.BytesIO(data)))
                        txt = ocr_text(img)
                        print("---- OCR TEXT START ----")
                        print(txt)
                        print("---- OCR TEXT END ----")
                        pairs = extract_pairs(txt)
                        if not pairs:
                            print(f"[WARN] no pairs found in {href}")
                        for sn, nm in pairs:
                            print(f"[PAIR] {sn} → {nm}")
                            mapping[sn] = nm
                        seen[href] = time.time()
                    except Exception as e:
                        print(f"[ERROR] {href}: {e}")
                upload_csv(mapping)
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump({"seen": seen, "map": mapping}, f, ensure_ascii=False, indent=2)
            else:
                print("[INFO] No new files")
        except Exception as e:
            print(f"[ERROR] Loop: {e}")
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
