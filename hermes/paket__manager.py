#!/usr/bin/env python3
import os, sqlite3
from datetime import datetime
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import StringVar, END
import tkinter as tk 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "paket.db")
os.makedirs(BASE_DIR, exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS packages(
  sendungsnr TEXT PRIMARY KEY,
  zone TEXT,
  received_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
c.execute("""CREATE TABLE IF NOT EXISTS directory(
  sendungsnr TEXT PRIMARY KEY,
  lastname TEXT,
  firstname TEXT,
  plz TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()

active_zone = None

def set_zone(z):
    global active_zone
    active_zone = z.upper()
    zone_var.set(f"Aktive Zone: {active_zone}")
    scan_entry.focus_set()

def handle_scan(event=None):
    val = scan_var.get().strip().replace(" ", "")
    scan_var.set("")
    if not val:
        return
    u = val.upper()
    if u.startswith("ZONE:"):
        seg = u.split(":",1)[1]
        if seg in ZONES:
            set_zone(seg)
            log(f"Zone {active_zone} aktiviert")
        else:
            log("Unbekannte Zone")
        return
    if active_zone is None:
        log("Bitte Zone scannen")
        return
    ts = datetime.now().isoformat(timespec="seconds")
    c.execute("REPLACE INTO packages(sendungsnr,zone,received_at) VALUES(?,?,?)",(val,active_zone,ts))
    conn.commit()
    log(f"{val} → {active_zone}")

def run_search(event=None):
    term = search_var.get().strip()
    result_list.delete(0, END)
    if not term:
        return
    like = f"%{term.lower()}%"
    rows = c.execute(
        """
        SELECT p.sendungsnr,
               TRIM(COALESCE(d.lastname,'')) AS ln,
               TRIM(COALESCE(d.firstname,'')) AS fn,
               p.zone,
               p.received_at
        FROM packages p
        LEFT JOIN directory d ON d.sendungsnr=p.sendungsnr
        WHERE lower(p.sendungsnr) LIKE ?
           OR lower(COALESCE(d.lastname,'')) LIKE ?
           OR lower(COALESCE(d.firstname,'')) LIKE ?
        ORDER BY p.received_at DESC
        LIMIT 300
        """,
        (like, like, like)
    ).fetchall()
    if not rows:
        result_list.insert(END, "Kein Treffer")
        return
    for sn, ln, fn, zone, ts in rows:
        name = f"{ln}, {fn}".strip(", ").strip()
        label = f"{sn}  {'— '+name if name else ''}  → {zone}  ({ts})"
        result_list.insert(END, label)

def delete_selected():
    sel = result_list.curselection()
    if not sel:
        return
    line = result_list.get(sel[0])
    if "→" not in line:
        return
    sn = line.split("  ")[0].strip()
    c.execute("DELETE FROM packages WHERE sendungsnr=?", (sn,))
    conn.commit()
    result_list.delete(sel[0])
    log(f"{sn} gelöscht")

def clear_search():
    search_var.set("")
    result_list.delete(0, END)
    scan_entry.focus_set()

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    log_list.insert(0, f"[{ts}] {msg}")
    if log_list.size() > 400:
        log_list.delete(400, END)

def focus_scan():
    scan_entry.focus_set()

def toggle_fullscreen(event=None):
    state = app.attributes("-fullscreen")
    app.attributes("-fullscreen", not state)

def quit_app(event=None):
    try:
        conn.commit()
        conn.close()
    except:
        pass
    app.destroy()

ZONES = ["A1","A2","A3","B1","B2","B3","C1","C2","C3"]

app = ttk.Window(title="Paket-Zonen-Manager", themename="flatly")
app.geometry("1024x600+0+0")
app.attributes("-fullscreen", True)
app.bind("<F11>", toggle_fullscreen)
app.bind("<Control-q>", quit_app)

zone_var = StringVar(value="Keine Zone aktiv")
scan_var = StringVar()
search_var = StringVar()

top = ttk.Frame(app, padding=12)
top.pack(fill=X)
zone_lbl = ttk.Label(top, textvariable=zone_var, font=("Arial", 28, "bold"))
zone_lbl.pack(side=LEFT)

ctrls = ttk.Frame(app, padding=(12,0))
ctrls.pack(fill=X)
ttk.Button(ctrls, text="Vollbild", bootstyle=SECONDARY, command=toggle_fullscreen).pack(side=RIGHT, padx=6)
ttk.Button(ctrls, text="Beenden", bootstyle=DANGER, command=quit_app).pack(side=RIGHT, padx=6)

scan_box = ttk.Frame(app, padding=(12,8))
scan_box.pack(fill=X)
ttk.Label(scan_box, text="Scan (Zonen-QR oder Sendungsnummer):", font=("Arial", 20)).pack(anchor=W)
scan_entry = ttk.Entry(scan_box, textvariable=scan_var, font=("Consolas", 26))
scan_entry.pack(fill=X, pady=6)
scan_entry.bind("<Return>", handle_scan)
scan_entry.focus_set()

zones = ttk.Frame(app, padding=(12,4))
zones.pack(fill=X)
grid = ttk.Frame(zones)
grid.pack()
btn_style_map = {
    0: PRIMARY,
    1: INFO,
    2: SUCCESS
}
idx = 0
for r in range(3):
    for ccol in range(3):
        z = ZONES[idx]
        style = btn_style_map[r]
        b = ttk.Button(grid, text=f"Zone {z}", bootstyle=style, command=lambda zz=z: set_zone(zz))
        b.grid(row=r, column=ccol, padx=8, pady=8, ipadx=24, ipady=24, sticky="nsew")
        grid.grid_columnconfigure(ccol, weight=1)
        idx += 1

search_box = ttk.Frame(app, padding=(12,8))
search_box.pack(fill=X)
ttk.Label(search_box, text="Suche (Name oder letzte Ziffern):", font=("Arial", 20)).grid(row=0, column=0, sticky=W)
search_entry = ttk.Entry(search_box, textvariable=search_var, font=("Consolas", 26), width=18)
search_entry.grid(row=0, column=1, padx=8)
ttk.Button(search_box, text="Suchen", bootstyle=SECONDARY, command=run_search).grid(row=0, column=2, padx=6, ipadx=18, ipady=12)
ttk.Button(search_box, text="Leeren", bootstyle=WARNING, command=clear_search).grid(row=0, column=3, padx=6, ipadx=18, ipady=12)
ttk.Button(search_box, text="Scan-Fokus", bootstyle=PRIMARY, command=focus_scan).grid(row=0, column=4, padx=6, ipadx=18, ipady=12)

lists = ttk.Frame(app, padding=(12,6))
lists.pack(fill=BOTH, expand=YES)
result_list = tk.Listbox(lists, font=("Consolas", 20), height=8)
result_list.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=(0,8))

log_list = tk.Listbox(lists, font=("Consolas", 14), height=6)
log_list.pack(fill=tk.BOTH, expand=True, side=tk.RIGHT)

actions = ttk.Frame(app, padding=(12,6))
actions.pack(fill=X)
ttk.Button(actions, text="Treffer löschen", bootstyle=DANGER, command=delete_selected).pack(side=LEFT, padx=6, ipadx=18, ipady=12)

app.mainloop()
