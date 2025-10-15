#!/usr/bin/env python3
import os, sqlite3
from datetime import datetime
import ttkbootstrap as ttk
import tkinter as tk

# --- Pfade & DB ---
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

# --- Farben (nie grau) ---
ARAL_BLUE = "#0078D7"
ARAL_RED  = "#D00000"
WHITE     = "#FFFFFF"

# --- State ---
active_zone = None
einbuchen_mode = False
zone_buttons: dict[str, tk.Button] = {}

# --- Hilfsfunktionen ---
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    log_list.insert(0, f"[{ts}] {msg}")
    if log_list.size() > 400:
        log_list.delete(400, tk.END)

def set_zone(z: str):
    """Nur im Einbuchen-Modus wird die aktive Zone gesetzt; sonst ignorieren (aber nie grau darstellen)."""
    global active_zone
    if not einbuchen_mode:
        return
    active_zone = z
    for name, btn in zone_buttons.items():
        if name == z:
            btn.config(bg=ARAL_BLUE, fg=WHITE, activebackground=ARAL_BLUE, activeforeground=WHITE)
        else:
            btn.config(bg=WHITE, fg=ARAL_BLUE, activebackground=WHITE, activeforeground=ARAL_BLUE)
    zone_var.set(f"Aktive Zone: {active_zone}")
    log(f"Zone {active_zone} gewählt")
    search_entry.focus_set()

def highlight_zone(z: str, color: str):
    """Zone visuell hervorheben (z. B. bei Suchtreffer rot)."""
    btn = zone_buttons.get(z)
    if not btn:
        return
    if color == "red":
        btn.config(bg=ARAL_RED, fg=WHITE, activebackground=ARAL_RED, activeforeground=WHITE)
    elif color == "blue":
        btn.config(bg=ARAL_BLUE, fg=WHITE, activebackground=ARAL_BLUE, activeforeground=WHITE)
    elif color == "white":
        btn.config(bg=WHITE, fg=ARAL_BLUE, activebackground=WHITE, activeforeground=ARAL_BLUE)

def reset_zone_colors():
    for btn in zone_buttons.values():
        btn.config(bg=WHITE, fg=ARAL_BLUE, activebackground=WHITE, activeforeground=ARAL_BLUE)

def handle_scan_or_enter(event=None):
    """Enter aus Suchfeld oder Scanner: je nach Modus suchen oder einbuchen."""
    val = search_var.get().strip().replace(" ", "")
    if not val:
        return
    if einbuchen_mode:
        # Einbuchen benötigt gewählte Zone
        if not active_zone:
            log("Bitte Zone wählen (Einbuchen aktiv)")
            return
        ts = datetime.now().isoformat(timespec="seconds")
        c.execute("REPLACE INTO packages(sendungsnr,zone,received_at) VALUES(?,?,?)",
                  (val, active_zone, ts))
        conn.commit()
        log(f"{val} → {active_zone}")
        search_var.set("")  # Eingabe leeren
        return
    else:
        # Standardmodus: Suche
        run_search()

def run_search(event=None):
    term = search_var.get().strip()
    result_list.delete(0, tk.END)
    reset_zone_colors()
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
    # Trefferliste + Zonen markieren
    seen_zones = set()
    for sn, ln, fn, zone, ts in rows:
        name = f"{ln}, {fn}".strip(", ").strip()
        label = f"{sn}  {'— '+name if name else ''}  → {zone if zone else '-'}  ({ts})"
        result_list.insert(tk.END, label)
        if zone:
            seen_zones.add(zone)
    for z in seen_zones:
        highlight_zone(z, "red")

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

def toggle_einbuchen():
    """Einbuchen an/aus. Button bleibt an gleicher Stelle; Text/Farbe wechseln."""
    global einbuchen_mode, active_zone
    einbuchen_mode = not einbuchen_mode
    active_zone = None
    reset_zone_colors()
    if einbuchen_mode:
        einbuchen_btn.config(text="Fertig", bg=ARAL_RED, fg=WHITE,
                             activebackground=ARAL_RED, activeforeground=WHITE)
        zone_var.set("Einbuchen aktiv – bitte Zone wählen")
        log("Einbuchen aktiviert")
    else:
        einbuchen_btn.config(text="Einbuchen", bg=ARAL_BLUE, fg=WHITE,
                             activebackground=ARAL_BLUE, activeforeground=WHITE)
        zone_var.set("Suche aktiv")
        log("Einbuchen beendet")
    search_entry.focus_set()

# --- GUI Grundgerüst ---
app = ttk.Window(title="Paket-Zonen-Manager", themename="flatly")
app.geometry("1280x800+0+0")
app.attributes("-fullscreen", False)  # bei Bedarf True setzen

zone_var   = tk.StringVar(value="Suche aktiv")
search_var = tk.StringVar()

# Kopf (Statuszeile minimal)
top = ttk.Frame(app, padding=8)
top.pack(fill=tk.X)
ttk.Label(top, textvariable=zone_var, font=("Arial", 22, "bold")).pack(side=tk.LEFT)

# Eingabezeile (Suche immer aktiv; Enter/Scanner triggert)
search_row = ttk.Frame(app, padding=(12, 6))
search_row.pack(fill=tk.X)
ttk.Label(search_row, text="Eingabe (Name / Nummer):", font=("Arial", 18)).grid(row=0, column=0, sticky=tk.W, padx=(0,10))
search_entry = ttk.Entry(search_row, textvariable=search_var, font=("Consolas", 26), width=22)
search_entry.grid(row=0, column=1, sticky=tk.W)
search_entry.bind("<Return>", handle_scan_or_enter)
search_entry.focus_set()

# --- Zonenbereich (mit Steuerbereich oben rechts über E-4/E) ---
zones_frame = tk.Frame(app, bg=WHITE, padx=12, pady=8)
zones_frame.pack(fill=tk.BOTH, expand=True)

grid = tk.Frame(zones_frame, bg=WHITE)
grid.pack(expand=True, anchor="center", fill=tk.BOTH)

# Grid: Spalten 0..4
for col in range(5):
    grid.grid_columnconfigure(col, weight=(2 if col <= 2 else 1))  # Regalblock etwas gewichtiger
# Zeilen: 0=Steuerleiste rechts, 1..4=A..D, 5=E-Reihe
for row in range(6):
    grid.grid_rowconfigure(row, weight=(0 if row == 0 else 1))

def make_zone_btn(name, r, c, colspan=1, rowspan=1, font_size=44, pad=14, bg=WHITE, fg=ARAL_BLUE):
    btn = tk.Button(
        grid,
        text=name,
        command=lambda z=name: set_zone(z),
        font=("Arial", font_size, "bold"),
        bg=bg,
        fg=fg,
        activebackground=bg,   # nie grau
        activeforeground=fg,
        relief="flat",
        borderwidth=0
    )
    btn.grid(row=r, column=c, columnspan=colspan, rowspan=rowspan,
             padx=pad, pady=pad, sticky="nsew")
    zone_buttons[name] = btn
    return btn

# Steuerbereich (oben rechts, über E-4/E): große Buttons
ctrl = tk.Frame(grid, bg=WHITE)
ctrl.grid(row=0, column=3, columnspan=2, sticky="nsew", padx=14, pady=(14, 0))
for j in range(2):
    ctrl.grid_columnconfigure(j, weight=1)
ctrl.grid_rowconfigure(0, weight=1)

einbuchen_btn = tk.Button(
    ctrl, text="Einbuchen", font=("Arial", 24, "bold"),
    bg=ARAL_BLUE, fg=WHITE, activebackground=ARAL_BLUE, activeforeground=WHITE,
    relief="flat", borderwidth=0, padx=24, pady=16, command=toggle_einbuchen
)
einbuchen_btn.grid(row=0, column=0, columnspan=2, sticky="nsew", ipadx=10, ipady=10)

# Regalböden A–D (links, gleich breit, enden bei Spalte 2)
make_zone_btn("A", 1, 0, colspan=3, font_size=48)
make_zone_btn("B", 2, 0, colspan=3, font_size=48)
make_zone_btn("C", 3, 0, colspan=3, font_size=48)
make_zone_btn("D", 4, 0, colspan=3, font_size=48)

# Untere Reihe: E-1, E-2, E-3 (bündig unter Regal), E-4 rechts daneben, E ganz rechts
make_zone_btn("E-1", 5, 0, font_size=40)
make_zone_btn("E-2", 5, 1, font_size=40)
make_zone_btn("E-3", 5, 2, font_size=40)   # bündig rechts mit dem Regal
make_zone_btn("E-4", 5, 3, font_size=40)   # daneben rechts
make_zone_btn("E",   5, 4, font_size=40)   # ganz rechts außen

# Listen unten
lists = ttk.Frame(app, padding=(12, 6))
lists.pack(fill=tk.BOTH, expand=True)
result_list = tk.Listbox(lists, font=("Consolas", 18), height=7)
result_list.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=(0, 8))
log_list = tk.Listbox(lists, font=("Consolas", 14), height=7)
log_list.pack(fill=tk.BOTH, expand=True, side=tk.RIGHT)

# Optional: Treffer löschen (hilfreich im Betrieb)
actions = ttk.Frame(app, padding=(12, 6))
actions.pack(fill=tk.X)
ttk.Button(actions, text="Treffer löschen", bootstyle="danger", command=delete_selected).pack(side=tk.LEFT, padx=6, ipadx=16, ipady=10)

# Startfokus
search_entry.focus_set()

# Run
app.mainloop()
