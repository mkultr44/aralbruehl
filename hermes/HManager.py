#!/usr/bin/env python3
import os, sqlite3
from datetime import datetime
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
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

ARAL_BLUE = "#0078D7"
ARAL_RED = "#D00000"
WHITE = "#FFFFFF"

active_zone = None
einbuchen_mode = False
zone_buttons = {}

def set_zone(z):
    global active_zone
    if not einbuchen_mode:
        return
    active_zone = z
    for zz, btn in zone_buttons.items():
        if zz == z:
            btn.config(bg=ARAL_BLUE, fg=WHITE)
        else:
            btn.config(bg=WHITE, fg=ARAL_BLUE)
    zone_var.set(f"Aktive Zone: {active_zone}")
    log(f"Zone {active_zone} gewählt")

def handle_scan(event=None):
    val = scan_var.get().strip().replace(" ", "")
    scan_var.set("")
    if not val:
        return
    if active_zone is None:
        log("Bitte zuerst Zone wählen (Einbuchen aktivieren)")
        return
    ts = datetime.now().isoformat(timespec="seconds")
    c.execute("REPLACE INTO packages(sendungsnr,zone,received_at) VALUES(?,?,?)",(val,active_zone,ts))
    conn.commit()
    log(f"{val} → {active_zone}")

def run_search(event=None):
    term = search_var.get().strip()
    result_list.delete(0, tk.END)
    for z in zone_buttons.values():
        z.config(bg=WHITE, fg=ARAL_BLUE)
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
        result_list.insert(tk.END, "Kein Treffer")
        return
    for sn, ln, fn, zone, ts in rows:
        name = f"{ln}, {fn}".strip(", ").strip()
        label = f"{sn}  {'— '+name if name else ''}  → {zone}  ({ts})"
        result_list.insert(tk.END, label)
        if zone in zone_buttons:
            zone_buttons[zone].config(bg=ARAL_RED, fg=WHITE)

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
    result_list.delete(0, tk.END)
    for z in zone_buttons.values():
        z.config(bg=WHITE, fg=ARAL_BLUE)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    log_list.insert(0, f"[{ts}] {msg}")
    if log_list.size() > 400:
        log_list.delete(400, tk.END)

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

def toggle_einbuchen():
    global einbuchen_mode, active_zone
    einbuchen_mode = not einbuchen_mode
    active_zone = None
    if einbuchen_mode:
        einbuchen_btn.config(text="Fertig", bg=ARAL_RED, fg=WHITE)
        zone_var.set("Einbuchen aktiv – bitte Zone wählen")
        for btn in zone_buttons.values():
            btn.config(state="normal")
    else:
        einbuchen_btn.config(text="Einbuchen", bg=ARAL_BLUE, fg=WHITE)
        zone_var.set("Einbuchen aus")
        for btn in zone_buttons.values():
            btn.config(state="disabled", bg=WHITE, fg=ARAL_BLUE)

ZONES = ["A","B","C","D-1","D-2","D-3","D-4","E"]

app = ttk.Window(title="Paket-Zonen-Manager", themename="flatly")
app.geometry("1024x600+0+0")
app.attributes("-fullscreen", True)
app.bind("<F11>", toggle_fullscreen)
app.bind("<Control-q>", quit_app)

zone_var = tk.StringVar(value="Keine Zone aktiv")
scan_var = tk.StringVar()
search_var = tk.StringVar()

top = ttk.Frame(app, padding=12)
top.pack(fill=X)
zone_lbl = ttk.Label(top, textvariable=zone_var, font=("Arial", 28, "bold"))
zone_lbl.pack(side=LEFT)

# Eingabe / Suche
search_box = ttk.Frame(app, padding=(12,8))
search_box.pack(fill=X)
ttk.Label(search_box, text="Suche (Name oder Nummer):", font=("Arial", 20)).grid(row=0, column=0, sticky=W)
search_entry = ttk.Entry(search_box, textvariable=search_var, font=("Consolas", 26), width=18)
search_entry.grid(row=0, column=1, padx=8)
ttk.Button(search_box, text="Suchen", bootstyle=SECONDARY, command=run_search).grid(row=0, column=2, padx=6, ipadx=18, ipady=12)
ttk.Button(search_box, text="Leeren", bootstyle=WARNING, command=clear_search).grid(row=0, column=3, padx=6, ipadx=18, ipady=12)
einbuchen_btn = tk.Button(search_box, text="Einbuchen", font=("Arial", 20, "bold"), bg=ARAL_BLUE, fg=WHITE, command=toggle_einbuchen)
einbuchen_btn.grid(row=0, column=4, padx=6, ipadx=18, ipady=12)
ttk.Button(search_box, text="Beenden", bootstyle=DANGER, command=quit_app).grid(row=0, column=5, padx=6, ipadx=18, ipady=12)

# Zonenlayout
zones_frame = tk.Frame(app, bg=WHITE, padx=12, pady=20)
zones_frame.pack(fill=tk.BOTH, expand=True)
grid = tk.Frame(zones_frame, bg=WHITE)
grid.pack(expand=True, anchor="center")

for col in range(5):
    grid.grid_columnconfigure(col, weight=1, minsize=150)
for row in range(4):
    grid.grid_rowconfigure(row, weight=(3 if row <= 2 else 1))

def make_zone_btn(txt, row, col, colspan=1, w=1.0, h=1.0):
    base = 120
    btn = tk.Button(
        grid,
        text=txt,
        command=lambda z=txt: set_zone(z),
        font=("Arial", 44, "bold"),
        fg=ARAL_BLUE,
        bg=WHITE,
        activebackground=ARAL_BLUE,
        activeforeground=WHITE,
        width=int(6 * w),
        height=int(2 * h),
        relief="solid",
        bd=8,
        state="disabled"
    )
    btn.grid(
        row=row,
        column=col,
        columnspan=colspan,
        padx=10,
        pady=10,
        ipadx=int(base * w),
        ipady=int(base * h * 0.7),
        sticky="nsew"
    )
    zone_buttons[txt] = btn

make_zone_btn("A", 0, 0, colspan=3, w=3.0, h=1.0)
make_zone_btn("B", 1, 0, colspan=3, w=3.0, h=1.0)
make_zone_btn("C", 2, 0, colspan=3, w=3.0, h=1.0)
make_zone_btn("D-1", 3, 0, w=1.0, h=1.0)
make_zone_btn("D-2", 3, 1, w=1.0, h=1.0)
make_zone_btn("D-3", 3, 2, w=1.0, h=1.0)
make_zone_btn("D-4", 3, 3, w=1.0, h=1.0)
make_zone_btn("E",   3, 4, w=2.0, h=1.0)

# Ergebnislisten
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
