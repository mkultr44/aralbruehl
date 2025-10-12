#!/usr/bin/env python3
import os, time, io, json, re, csv, base64
from urllib.parse import urlparse
import requests
from lxml import etree
from PIL import Image, ImageOps, ImageFilter
import pillow_heif
import pytesseract
from dotenv import load_dotenv

load_dotenv()

SRC_URL = os.environ.get("SOURCE_SHARE_URL").strip()
DST_URL = os.environ.get("DEST_SHARE_URL").strip()
OUT_NAME = os.environ.get("OUTPUT_FILENAME","hermes_directory.csv").strip()
INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS","30"))
STATE_PATH = os.environ.get("STATE_FILE",".state.json")
OCR_LANG = os.environ.get("OCR_LANG","eng")

def token_from_share(u):
    p = urlparse(u)
    seg = [s for s in p.path.split("/") if s]
    i = seg.index("s")
    return seg[i+1]

SRC_TOKEN = token_from_share(SRC_URL)
DST_TOKEN = token_from_share(DST_URL)

SRC_DAV = f"https://{urlparse(SRC_URL).netloc}/remote.php/dav/public-files/{SRC_TOKEN}/"
DST_DAV = f"https://{urlparse(DST_URL).netloc}/remote.php/dav/public-files/{DST_TOKEN}/"

AUTH_SRC = (SRC_TOKEN, "")
AUTH_DST = (DST_TOKEN, "")

NAMES = {}

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH,"r",encoding="utf-8") as f:
            return json.load(f)
    return {"seen":{}}

def save_state(st):
    with open(STATE_PATH,"w",encoding="utf-8") as f:
        json.dump(st,f,ensure_ascii=False,indent=2)

def propfind(url, auth):
    headers={"Depth":"1"}
    body='''<?xml version="1.0"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:getlastmodified/>
    <d:getcontenttype/>
    <d:getcontentlength/>
    <d:getetag/>
  </d:prop>
</d:propfind>'''
    r = requests.request("PROPFIND", url, data=body, headers=headers, auth=auth, timeout=30)
    r.raise_for_status()
    return r.text

def list_images():
    xml = propfind(SRC_DAV, AUTH_SRC)
    ns = {"d":"DAV:"}
    root = etree.fromstring(bytes(xml, "utf-8"))
    items=[]
    for resp in root.findall("d:response", ns):
        href = resp.findtext("d:href", namespaces=ns)
        if not href or href.endswith("/"):
            continue
        etag = resp.find(".//d:getetag", ns)
        ctype = resp.find(".//d:getcontenttype", ns)
        name = href.strip("/").split("/")[-1]
        et = etag.text.strip('"') if etag is not None and etag.text else ""
        ct = ctype.text if ctype is not None else ""
        if any(ct.lower().startswith(x) for x in ["image/","application/octet-stream"]) or name.lower().endswith((".jpg",".jpeg",".png",".heic",".heif",".webp",".bmp",".tif",".tiff")):
            items.append((name, et))
    return items

def download_file(name):
    url = SRC_DAV + name
    r = requests.get(url, auth=AUTH_SRC, timeout=60)
    r.raise_for_status()
    return r.content

def open_image(data, name):
    ext = name.lower().split(".")[-1]
    if ext in ("heic","heif"):
        heif = pillow_heif.read_heif(io.BytesIO(data))
        img = Image.frombytes(heif.mode, heif.size, heif.data, "raw")
        return img
    return Image.open(io.BytesIO(data)).convert("RGB")

def preprocess(img):
    g = ImageOps.grayscale(img)
    g = ImageOps.autocontrast(g)
    g = g.filter(ImageFilter.MedianFilter(size=3))
    g = g.point(lambda p: 255 if p>180 else (0 if p<80 else p))
    return g

def ocr_text(img):
    cfg = "--oem 3 --psm 6"
    return pytesseract.image_to_string(img, lang=OCR_LANG, config=cfg)

def extract_pairs(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    pairs=[]
    nums=[]
    for l in lines:
        for m in re.finditer(r"\b(\d[\d\- ]{7,})\b", l):
            s = re.sub(r"\D","",m.group(1))
            if 8 <= len(s) <= 22:
                nums.append((s,l))
    for num, ctx in nums:
        idx = lines.index(ctx) if ctx in lines else -1
        window = []
        if idx!=-1:
            if idx>0: window.append(lines[idx-1])
            window.append(lines[idx])
            if idx+1<len(lines): window.append(lines[idx+1])
        chunk = "  ".join(window)
        m = re.search(r"([A-ZÄÖÜ][a-zäöüß\-']{1,}\s+[A-ZÄÖÜ][a-zäöüß\-']{1,})", chunk)
        if not m:
            m = re.search(r"([A-ZÄÖÜ][a-zäöüß\-']{1,}),\s*([A-ZÄÖÜ][a-zäöüß\-']{1,})", chunk)
            if m:
                name = f"{m.group(1)} {m.group(2)}"
            else:
                m2 = re.search(r"Name[:\s]+([A-ZÄÖÜ][^\d,]{2,})", chunk)
                name = m2.group(1).strip() if m2 else ""
        else:
            name = m.group(1).strip()
        name = re.sub(r"\s{2,}"," ",name).strip()
        if name:
            pairs.append((num,name))
    return pairs

def merge_map(cur_map, pairs):
    for num,name in pairs:
        if num not in cur_map or len(name)>len(cur_map[num]):
            cur_map[num]=name

def write_csv_upload(cur_map):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["sendungsnummer","name"])
    for k in sorted(cur_map.keys()):
        w.writerow([k, cur_map[k]])
    data = out.getvalue().encode("utf-8")
    url = DST_DAV + OUT_NAME
    r = requests.put(url, data=data, auth=AUTH_DST, headers={"Content-Type":"text/csv; charset=utf-8"}, timeout=60)
    r.raise_for_status()

def main():
    state = load_state()
    seen = state.get("seen",{})
    cur_map = {}
    while True:
        try:
            items = list_images()
            new = []
            for name, etag in items:
                prev = seen.get(name)
                if prev != etag:
                    new.append((name, etag))
            if new:
                for name, etag in new:
                    try:
                        blob = download_file(name)
                        img = open_image(blob, name)
                        img = preprocess(img)
                        txt = ocr_text(img)
                        pairs = extract_pairs(txt)
                        merge_map(cur_map, pairs)
                        seen[name]=etag
                    except Exception:
                        seen[name]=etag
                if cur_map:
                    write_csv_upload(cur_map)
                state["seen"]=seen
                save_state(state)
        except Exception:
            pass
        time.sleep(INTERVAL)

if __name__=="__main__":
    main()
