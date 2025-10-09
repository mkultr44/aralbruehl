#!/usr/bin/env python3
import sqlite3, time, threading
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

DB_PATH = "/home/pi/paket.db"

# ---------- Datenbank vorbereiten ----------
conn = sqlite3.connect("paket.db")
c = conn.cursor()
c.execute("""CREATE TABLE IF NOT EXISTS packages(
    sendungsnr TEXT PRIMARY KEY,
    zone TEXT,
    received_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
conn.commit()

active_zone = None
lock = threading.Lock()

# ---------- Funktionen ----------
def set_zone(zone):
    global active_zone
    with lock:
        active_zone = zone
    zone_label.config(text=f"Aktive Zone: {zone}", bg="#007bff", fg="white")
    log(f"Zone gesetzt auf {zone}")

def scan_input(event=None):
    code = entry.get().strip().replace(" ", "")
    entry.delete(0, tk.END)
    if not code:
        return
    # Zonen-QR erkennen
    if code.upper().startswith("ZONE:"):
        set_zone(code.split(":")[1].upper())
        return
    if not active_zone:
        log("⚠️ Bitte zuerst Zone scannen.")
        return
    with lock:
        c.execute("REPLACE INTO packages (sendungsnr, zone, received_at) VALUES (?,?,?)",
                  (code, active_zone, datetime.now().isoformat(timespec='seconds')))
        conn.commit()
    log(f"Paket {code} → Zone {active_zone}")

def search_package():
    term = search_entry.get().strip()
    if not term:
        return
    term = term.lower()
    c.execute("SELECT sendungsnr, zone, received_at FROM packages WHERE lower(sendungsnr) LIKE ?", ('%'+term,))
    rows = c.fetchall()
    result_box.delete(0, tk.END)
    if rows:
        for r in rows:
            result_box.insert(tk.END, f"{r[0]} → {r[1]} ({r[2]})")
    else:
        result_box.insert(tk.END, "Kein Treffer")

def delete_selected():
    sel = result_box.curselection()
    if not sel:
        return
    line = result_box.get(sel[0])
    sn = line.split("→")[0].strip()
    c.execute("DELETE FROM packages WHERE sendungsnr=?", (sn,))
    conn.commit()
    result_box.delete(sel)
    log(f"Paket {sn} gelöscht")

def log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    log_box.insert(0, f"[{now}] {msg}")
    if len(log_box.get(0, tk.END)) > 200:
        log_box.delete(199, tk.END)

def cleanup_old():
    while True:
        time.sleep(3600)
        cutoff = datetime.now().timestamp() - 30*24*3600
        c.execute("DELETE FROM packages WHERE strftime('%s', received_at) < ?", (cutoff,))
        conn.commit()

# ---------- GUI ----------
root = tk.Tk()
root.title("Paket-Zonen-Manager")
root.geometry("1024x600")
root.configure(bg="#f4f6fb")

frame_top = tk.Frame(root, bg="#f4f6fb")
frame_top.pack(pady=10)

zone_label = tk.Label(frame_top, text="Keine Zone aktiv", font=("Arial", 20, "bold"), bg="#f4f6fb")
zone_label.pack()

entry = tk.Entry(frame_top, font=("Consolas", 22), width=25)
entry.pack(pady=10)
entry.focus()
entry.bind("<Return>", scan_input)

frame_mid = tk.Frame(root, bg="#f4f6fb")
frame_mid.pack(pady=10)

tk.Label(frame_mid, text="Suche (Name / letzte Ziffern):", bg="#f4f6fb").grid(row=0, column=0, sticky="w")
search_entry = tk.Entry(frame_mid, font=("Consolas", 18), width=20)
search_entry.grid(row=0, column=1, padx=10)
ttk.Button(frame_mid, text="Suchen", command=search_package).grid(row=0, column=2)
ttk.Button(frame_mid, text="Löschen", command=delete_selected).grid(row=0, column=3, padx=10)

result_box = tk.Listbox(root, font=("Consolas", 16), width=60, height=10)
result_box.pack(pady=5)

tk.Label(root, text="Log:", bg="#f4f6fb").pack()
log_box = tk.Listbox(root, font=("Consolas", 12), width=60, height=6)
log_box.pack(pady=5)

# Hintergrund-Cleanup
threading.Thread(target=cleanup_old, daemon=True).start()

root.mainloop()
