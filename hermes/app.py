#!/usr/bin/env python3
"""Paket-Zonen-Manager

Tkinter/ttkbootstrap-Oberfläche zum schnellen Erfassen von Paketen in
Lagerzonen. Kernfunktionen:

* Einbuchen über Scanner mit fuzzy Zuordnung von Namen (RapidFuzz)
* Periodische Synchronisation eines Nextcloud-Exports in die lokale
  SQLite-Datenbank
* Live-Suche mit fuzzy Matching
* Session-Counter und visuelle Zonensteuerung
"""

from __future__ import annotations

import csv
import io
import os
import sqlite3
import threading
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import ttkbootstrap as ttk
from rapidfuzz import fuzz, process

# --- Pfade & Konstanten ----------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "paket.db")
CSV_URL = (
    "https://nextcloud.aralbruehl.de/public.php/dav/files/"
    "mJAaPjgBycC7d7y/hermes_final.csv"
)
SYNC_INTERVAL_SECONDS = 30

ARAL_BLUE = "#0078D7"
ARAL_RED = "#D00000"
ARAL_GREEN = "#009F4D"
WHITE = "#FFFFFF"
TEXT_DARK = "#0A0A0A"

os.makedirs(BASE_DIR, exist_ok=True)


# --- Datenmodell -----------------------------------------------------------

DB_LOCK = threading.Lock()
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row


def _column_exists(table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def init_db() -> None:
    with DB_LOCK:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS packages (
                sendungsnr TEXT PRIMARY KEY,
                zone TEXT,
                received_at TEXT DEFAULT CURRENT_TIMESTAMP,
                name TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS directory (
                sendungsnr TEXT PRIMARY KEY,
                name TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        if not _column_exists("packages", "name"):
            conn.execute("ALTER TABLE packages ADD COLUMN name TEXT")
        if not _column_exists("directory", "name"):
            conn.execute("ALTER TABLE directory ADD COLUMN name TEXT")
        conn.commit()


init_db()


# --- Directory-Cache -------------------------------------------------------

@dataclass
class DirectoryEntry:
    sendungsnr: str
    name: str


directory_cache: Dict[str, DirectoryEntry] = {}
directory_choices: List[str] = []


def rebuild_directory_cache() -> None:
    global directory_cache, directory_choices
    with DB_LOCK:
        rows = conn.execute(
            "SELECT sendungsnr, COALESCE(name, '') AS name FROM directory"
        ).fetchall()
    cache = {
        row["sendungsnr"]: DirectoryEntry(row["sendungsnr"], row["name"].strip())
        for row in rows
        if row["sendungsnr"]
    }
    directory_cache = cache
    directory_choices = list(cache.keys())


rebuild_directory_cache()


# --- Tkinter Widgets (wird später initialisiert) ---------------------------

app: ttk.Window
search_var: tk.StringVar
zone_var: tk.StringVar
counter_var: tk.StringVar
search_entry: ttk.Entry
result_list: tk.Listbox
log_list: tk.Listbox
warning_label: tk.Label
einbuchen_btn: tk.Button
counter_value_lbl: tk.Label
counter_frame: ttk.Frame
result_panel: ttk.Frame
style: ttk.Style


# --- UI State --------------------------------------------------------------

active_zone: Optional[str] = None
einbuchen_mode: bool = False
zone_buttons: Dict[str, tk.Button] = {}
session_counter: int = 0
warning_job: Optional[str] = None
result_rows: List[Dict[str, str]] = []


# --- Hilfsfunktionen -------------------------------------------------------


def log(msg: str) -> None:
    """Nachricht in der Log-Liste anzeigen."""

    if "log_list" not in globals():
        return
    ts = datetime.now().strftime("%H:%M:%S")
    log_list.insert(0, f"[{ts}] {msg}")
    if log_list.size() > 400:
        log_list.delete(400, tk.END)


def log_async(msg: str) -> None:
    if "app" not in globals():
        return
    app.after(0, lambda: log(msg))


def ensure_focus() -> None:
    if "search_entry" in globals():
        search_entry.focus_set()
        search_entry.icursor(tk.END)


def init_styles() -> ttk.Style:
    """Initialisiert ttk Styles für ein konsistentes Erscheinungsbild."""

    style = ttk.Style()
    style.configure("White.TFrame", background=WHITE)
    style.configure("White.TLabel", background=WHITE, foreground=TEXT_DARK)
    style.configure(
        "Header.TLabel",
        background=WHITE,
        foreground=TEXT_DARK,
        font=("Arial", 20, "bold"),
    )
    style.configure(
        "CounterText.TLabel",
        background=WHITE,
        foreground="black",
        font=("Arial", 24, "bold"),
    )
    return style


def apply_listbox_theme(widget: tk.Listbox) -> None:
    """Sorgt für weiße Hintergründe und Aral-Auswahlfarben in Listboxen."""

    widget.configure(
        activestyle="none",
        background=WHITE,
        borderwidth=0,
        fg=TEXT_DARK,
        highlightbackground=ARAL_BLUE,
        highlightcolor=ARAL_BLUE,
        highlightthickness=1,
        relief="flat",
        selectbackground=ARAL_BLUE,
        selectforeground=WHITE,
    )


def update_counter_label() -> None:
    counter_var.set(str(session_counter))
    color = ARAL_RED if session_counter == 0 else ARAL_GREEN
    counter_value_lbl.config(fg=color)


def reset_zone_colors() -> None:
    for btn in zone_buttons.values():
        btn.config(bg=WHITE, fg=ARAL_BLUE, activebackground=WHITE, activeforeground=ARAL_BLUE)


def refresh_zone_highlights(selected_zone: Optional[str] = None) -> None:
    reset_zone_colors()
    if einbuchen_mode and active_zone:
        highlight_zone(active_zone, "blue")
    if selected_zone:
        highlight_zone(selected_zone, "red")


def show_result_panel(show: bool) -> None:
    if "result_panel" not in globals():
        return
    if show:
        result_panel.grid()
    else:
        result_panel.grid_remove()
    if "result_list" in globals() and not show:
        result_list.selection_clear(0, tk.END)


def highlight_zone(zone: str, color: str) -> None:
    btn = zone_buttons.get(zone)
    if not btn:
        return
    if color == "blue":
        btn.config(bg=ARAL_BLUE, fg=WHITE, activebackground=ARAL_BLUE, activeforeground=WHITE)
    elif color == "red":
        btn.config(bg=ARAL_RED, fg=WHITE, activebackground=ARAL_RED, activeforeground=WHITE)


def hide_zone_warning() -> None:
    global warning_job
    if "warning_label" not in globals():
        return
    warning_label.grid_remove()
    if warning_job is not None:
        app.after_cancel(warning_job)
        warning_job = None


def blink_warning(state: bool = True) -> None:
    global warning_job
    if "warning_label" not in globals():
        return
    warning_label.config(bg=ARAL_RED if state else WHITE, fg=WHITE if state else ARAL_RED)
    warning_job = app.after(400, blink_warning, not state)


def show_zone_warning() -> None:
    if "warning_label" not in globals():
        return
    warning_label.grid()
    blink_warning(True)


def set_zone(zone: str) -> None:
    global active_zone
    if not einbuchen_mode:
        return
    active_zone = zone
    hide_zone_warning()
    refresh_zone_highlights()
    zone_var.set(f"Aktive Zone: {active_zone}")
    log(f"Zone {active_zone} gewählt")
    ensure_focus()


def toggle_einbuchen() -> None:
    global einbuchen_mode, active_zone, session_counter
    einbuchen_mode = not einbuchen_mode
    active_zone = None
    refresh_zone_highlights()
    hide_zone_warning()
    if einbuchen_mode:
        session_counter = 0
        zone_var.set("Einbuchen aktiv – bitte Zone wählen")
        einbuchen_btn.config(
            text="Fertig",
            bg=ARAL_RED,
            fg=WHITE,
            activebackground=ARAL_RED,
            activeforeground=WHITE,
        )
        counter_frame.pack(side=tk.RIGHT)
        show_result_panel(False)
        log("Einbuchen gestartet")
    else:
        session_counter = 0
        zone_var.set("Suche aktiv")
        einbuchen_btn.config(
            text="Einbuchen",
            bg=ARAL_BLUE,
            fg=WHITE,
            activebackground=ARAL_BLUE,
            activeforeground=WHITE,
        )
        counter_frame.pack_forget()
        show_result_panel(True)
        run_search()
        log("Einbuchen beendet")
    update_counter_label()
    ensure_focus()


def match_directory(sendungsnr: str) -> Tuple[Optional[str], Sequence[str], Optional[int]]:
    """Fuzzy-Abgleich der Sendungsnummer gegen den Directory-Cache."""

    if not sendungsnr:
        return None, [], None

    key = sendungsnr.strip()
    entry = directory_cache.get(key)
    if entry:
        return entry.name or None, [key], 100

    if not directory_choices:
        return None, [], None

    matches = process.extract(
        key,
        directory_choices,
        scorer=fuzz.WRatio,
        processor=None,
        score_cutoff=85,
        limit=6,
    )
    if not matches:
        return None, [], None

    best_score = matches[0][1]
    best_key = matches[0][0]
    matched_keys = [choice for choice, _score, *_ in matches]

    if best_score >= 90:
        name = directory_cache.get(best_key)
        return (name.name if name else None), matched_keys, best_score

    plausible_names = {
        directory_cache[choice].name
        for choice, score, *_ in matches
        if 85 <= score <= 95 and choice in directory_cache and directory_cache[choice].name
    }
    combined = " / ".join(sorted(plausible_names)) if plausible_names else None
    return combined or None, matched_keys, best_score


def insert_package(sendungsnr: str, zone: str, name: Optional[str]) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with DB_LOCK:
        conn.execute(
            """
            INSERT INTO packages (sendungsnr, zone, received_at, name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sendungsnr) DO UPDATE SET
                zone=excluded.zone,
                received_at=excluded.received_at,
                name=excluded.name
            """,
            (sendungsnr, zone, ts, name),
        )
        conn.commit()


def handle_scan_or_enter(event: Optional[tk.Event] = None) -> str:
    global session_counter
    value = search_var.get().strip()

    if not value:
        if not einbuchen_mode:
            run_search()
        return "break"

    if einbuchen_mode:
        if not active_zone:
            log("Zone auswählen, bevor eingebucht wird")
            show_zone_warning()
            ensure_focus()
            return "break"
        name, matches, score = match_directory(value)
        insert_package(value, active_zone, name)
        session_counter += 1
        update_counter_label()
        log_msg = f"{value} → {active_zone}"
        if name:
            log_msg += f" ({name})"
        if score is not None:
            log_msg += f" [Score {score}]"
        elif matches:
            log_msg += " [Mehrfachtreffer]"
        log(log_msg)
        if matches and len(matches) > 1:
            log(f"Fuzzy Matches: {', '.join(matches)}")
        search_var.set("")
        ensure_focus()
        return "break"

    run_search()
    return "break"


def fetch_all_packages() -> List[sqlite3.Row]:
    with DB_LOCK:
        rows = conn.execute(
            """
            SELECT sendungsnr,
                   COALESCE(name, '') AS name,
                   COALESCE(zone, '') AS zone,
                   COALESCE(received_at, '') AS received_at
            FROM packages
            ORDER BY datetime(received_at) DESC
            LIMIT 500
            """
        ).fetchall()
    return list(rows)


def populate_result_list(
    items: Sequence[Mapping[str, Any]], *, empty_message: str
) -> None:
    result_rows.clear()
    if "result_list" not in globals():
        return
    result_list.delete(0, tk.END)
    refresh_zone_highlights()

    if not items:
        result_list.insert(tk.END, empty_message)
        return

    for item in items:
        sendungsnr = str(item.get("sendungsnr") or "").strip()
        if not sendungsnr:
            continue
        name = str(item.get("name") or "").strip()
        zone = str(item.get("zone") or "").strip()
        timestamp = str(item.get("received_at") or "").strip()
        score = item.get("score")

        label = f"{sendungsnr}"
        if name:
            label += f" — {name}"
        label += f" → {zone or '-'}"
        if timestamp:
            label += f" ({timestamp})"
        if score is not None and score != "":
            label += f"  [Score {score}]"

        result_list.insert(tk.END, label)
        result_rows.append({
            "sendungsnr": sendungsnr,
            "zone": zone,
        })

    if not result_rows and result_list.size() == 0:
        result_list.insert(tk.END, empty_message)


def display_packages(rows: Iterable[sqlite3.Row]) -> None:
    populate_result_list([dict(row) for row in rows], empty_message="Keine Pakete vorhanden")


def run_search(event: Optional[tk.Event] = None) -> None:
    term = search_var.get().strip()
    rows = fetch_all_packages()

    if not rows:
        populate_result_list([], empty_message="Keine Pakete vorhanden")
        return

    if not term:
        display_packages(rows)
        return

    choices: Dict[str, sqlite3.Row] = {}
    dataset: Dict[str, str] = {}
    for row in rows:
        key = row["sendungsnr"]
        choices[key] = row
        candidate = " ".join(
            part
            for part in (row["sendungsnr"], row["name"], row["zone"])
            if part
        )
        dataset[key] = candidate

    matches = process.extract(
        term,
        dataset,
        scorer=fuzz.WRatio,
        processor=None,
        score_cutoff=70,
        limit=200,
    )

    if not matches:
        populate_result_list([], empty_message="Kein Treffer")
        return

    sorted_rows: List[sqlite3.Row] = []
    seen_keys: set[str] = set()
    for key, score, _value in sorted(matches, key=lambda item: item[1], reverse=True):
        if key in seen_keys:
            continue
        row = choices.get(key)
        if not row:
            continue
        row = dict(row)
        row["score"] = score
        sorted_rows.append(row)
        seen_keys.add(key)

    populate_result_list(sorted_rows, empty_message="Kein Treffer")


def delete_selected() -> None:
    sel = result_list.curselection()
    if not sel:
        return
    line = result_list.get(sel[0])
    if "→" not in line:
        return
    sendungsnr = line.split(" → ")[0].split(" — ")[0].strip()
    with DB_LOCK:
        conn.execute("DELETE FROM packages WHERE sendungsnr=?", (sendungsnr,))
        conn.commit()
    result_list.delete(sel[0])
    if sel[0] < len(result_rows):
        del result_rows[sel[0]]
    refresh_zone_highlights()
    log(f"{sendungsnr} gelöscht")


def on_result_select(_event: tk.Event) -> None:
    sel = result_list.curselection()
    if not sel or sel[0] >= len(result_rows):
        refresh_zone_highlights()
        return
    zone = result_rows[sel[0]].get("zone") or ""
    refresh_zone_highlights(zone if zone else None)


# --- CSV Synchronisation ---------------------------------------------------


def parse_csv(content: str) -> List[Tuple[str, str]]:
    reader = csv.DictReader(io.StringIO(content))
    entries: List[Tuple[str, str]] = []
    for row in reader:
        sendungsnr = (
            row.get("sendungsnr")
            or row.get("Sendungsnummer")
            or row.get("sendungsnummer")
            or row.get("Sendungsnr")
        )
        if not sendungsnr:
            continue
        name = (
            row.get("name")
            or row.get("Name")
            or row.get("Nachname")
            or row.get("Empfänger")
            or ""
        ).strip()

        firstname = (
            row.get("Vorname") or row.get("vorname") or row.get("firstname") or ""
        ).strip()
        lastname = (
            row.get("Nachname") or row.get("nachname") or row.get("lastname") or ""
        ).strip()
        if not name:
            name = ", ".join(part for part in [lastname, firstname] if part).strip(", ")
        entries.append((sendungsnr.strip(), name))
    return entries


def download_csv() -> Optional[str]:
    import requests

    try:
        response = requests.get(CSV_URL, timeout=15)
        if response.status_code == 200:
            response.encoding = response.apparent_encoding or "utf-8"
            return response.text
        log_async(f"CSV Sync fehlgeschlagen (HTTP {response.status_code})")
    except Exception as exc:  # pragma: no cover - reine Laufzeitdiagnose
        log_async(f"CSV Sync Fehler: {exc}")
    return None


def sync_directory(entries: Sequence[Tuple[str, str]]) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with DB_LOCK:
        conn.execute("DELETE FROM directory")
        conn.executemany(
            """
            INSERT INTO directory (sendungsnr, name, updated_at)
            VALUES (?, ?, ?)
            """,
            ((sn, name, ts) for sn, name in entries),
        )
        conn.commit()
    rebuild_directory_cache()


def perform_sync() -> None:
    content = download_csv()
    if not content:
        return
    entries = parse_csv(content)
    if not entries:
        log_async("CSV Sync: keine Daten erhalten")
        return
    sync_directory(entries)
    log_async(f"CSV Sync abgeschlossen ({len(entries)} Einträge)")


def schedule_sync() -> None:
    def worker() -> None:
        perform_sync()
        app.after(SYNC_INTERVAL_SECONDS * 1000, schedule_sync)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


# --- GUI Aufbau ------------------------------------------------------------


def build_gui() -> None:
    global app, search_var, zone_var, counter_var
    global search_entry, result_list, log_list, warning_label, einbuchen_btn
    global counter_value_lbl, counter_frame, result_panel, style

    app = ttk.Window(title="Paket-Zonen-Manager", themename="flatly")
    app.geometry("1280x800")
    app.resizable(False, False)
    app.configure(background=WHITE)

    style = init_styles()

    zone_var = tk.StringVar(value="Suche aktiv")
    search_var = tk.StringVar()
    counter_var = tk.StringVar(value="0")

    # Kopfzeile
    top = ttk.Frame(app, padding=16, style="White.TFrame")
    top.pack(fill=tk.X)

    ttk.Label(
        top,
        textvariable=zone_var,
        font=("Arial", 26, "bold"),
        anchor=tk.W,
        style="White.TLabel",
    ).pack(side=tk.LEFT, fill=tk.X, expand=True)

    counter_frame = ttk.Frame(top, style="White.TFrame")
    ttk.Label(counter_frame, text="Eingebucht:", style="CounterText.TLabel").pack(
        side=tk.LEFT, padx=(0, 6)
    )
    counter_value_lbl = tk.Label(
        counter_frame,
        textvariable=counter_var,
        font=("Arial", 30, "bold"),
        fg=ARAL_RED,
        bg=WHITE,
    )
    counter_value_lbl.pack(side=tk.LEFT)

    # Eingabezeile
    search_row = ttk.Frame(app, padding=(16, 0), style="White.TFrame")
    search_row.pack(fill=tk.X, pady=(0, 8))
    ttk.Label(
        search_row,
        text="Eingabe (Scan / Suche):",
        font=("Arial", 20),
        style="White.TLabel",
    ).grid(row=0, column=0, sticky=tk.W, padx=(0, 12))
    search_entry = ttk.Entry(search_row, textvariable=search_var, font=("Consolas", 28), width=24)
    search_entry.grid(row=0, column=1, sticky=tk.W)
    search_entry.bind("<Return>", handle_scan_or_enter)
    search_entry.focus_set()

    ttk.Button(
        search_row,
        text="Suchen",
        bootstyle="primary",
        command=run_search,
    ).grid(row=0, column=2, padx=(12, 0))

    # Zonenbereich
    zones_frame = tk.Frame(app, bg=WHITE, padx=16, pady=16)
    zones_frame.pack(fill=tk.BOTH, expand=True)

    grid = tk.Frame(zones_frame, bg=WHITE)
    grid.pack(expand=True, fill=tk.BOTH)

    for col in range(5):
        weight = 2 if col <= 2 else 1
        grid.grid_columnconfigure(col, weight=weight)
    for row in range(6):
        grid.grid_rowconfigure(row, weight=(0 if row == 0 else 1))

    # Warnhinweis über Zone A
    warning_label = tk.Label(
        grid,
        text="Zone auswählen!",
        font=("Arial", 26, "bold"),
        bg=ARAL_RED,
        fg=WHITE,
        relief="flat",
        padx=16,
        pady=6,
    )
    warning_label.grid(row=0, column=0, columnspan=3, pady=(0, 8))
    warning_label.grid_remove()

    # Steuerbereich oben rechts
    ctrl = tk.Frame(grid, bg=WHITE)
    ctrl.grid(row=0, column=3, columnspan=2, rowspan=6, sticky="nsew", padx=14, pady=(0, 8))
    ctrl.grid_columnconfigure(0, weight=1)
    ctrl.grid_rowconfigure(0, weight=0)
    ctrl.grid_rowconfigure(1, weight=1)

    global zone_buttons
    zone_buttons = {}

    einbuchen_btn = tk.Button(
        ctrl,
        text="Einbuchen",
        font=("Arial", 26, "bold"),
        bg=ARAL_BLUE,
        fg=WHITE,
        activebackground=ARAL_BLUE,
        activeforeground=WHITE,
        relief="flat",
        borderwidth=0,
        padx=24,
        pady=18,
        command=toggle_einbuchen,
    )
    einbuchen_btn.grid(row=0, column=0, sticky="nsew", ipadx=10, ipady=10)

    result_panel = ttk.Frame(ctrl, padding=(0, 16, 0, 0), style="White.TFrame")
    result_panel.grid(row=1, column=0, sticky="nsew")
    ttk.Label(result_panel, text="Pakete", style="Header.TLabel").pack(anchor=tk.W)

    result_container = ttk.Frame(result_panel, style="White.TFrame")
    result_container.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
    result_scroll = ttk.Scrollbar(result_container, orient=tk.VERTICAL)
    result_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    result_list = tk.Listbox(
        result_container,
        font=("Consolas", 18),
        height=16,
        exportselection=False,
        yscrollcommand=result_scroll.set,
    )
    apply_listbox_theme(result_list)
    result_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    result_scroll.config(command=result_list.yview)
    result_list.bind("<<ListboxSelect>>", on_result_select)

    # Helper zum Erzeugen der Buttons
    def make_zone_btn(name: str, r: int, c: int, colspan: int = 1, font_size: int = 48) -> tk.Button:
        btn = tk.Button(
            grid,
            text=name,
            command=lambda z=name: set_zone(z),
            font=("Arial", font_size, "bold"),
            bg=WHITE,
            fg=ARAL_BLUE,
            activebackground=WHITE,
            activeforeground=ARAL_BLUE,
            relief="solid",
            bd=4,
            highlightthickness=0,
        )
        btn.grid(row=r, column=c, columnspan=colspan, padx=12, pady=12, sticky="nsew")
        zone_buttons[name] = btn
        return btn

    make_zone_btn("A", 1, 0, colspan=3)
    make_zone_btn("B", 2, 0, colspan=3)
    make_zone_btn("C", 3, 0, colspan=3)
    make_zone_btn("D", 4, 0, colspan=3)

    make_zone_btn("E-1", 5, 0, font_size=42)
    make_zone_btn("E-2", 5, 1, font_size=42)
    make_zone_btn("E-3", 5, 2, font_size=42)
    make_zone_btn("E-4", 5, 3, font_size=42)
    make_zone_btn("F", 5, 4, font_size=42)

    reset_zone_colors()

    # Protokoll-Liste
    log_panel = ttk.Frame(app, padding=(16, 8), style="White.TFrame")
    log_panel.pack(fill=tk.BOTH, expand=True)
    ttk.Label(log_panel, text="Protokoll", style="Header.TLabel").pack(anchor=tk.W)

    log_container = ttk.Frame(log_panel, style="White.TFrame")
    log_container.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
    log_scroll = ttk.Scrollbar(log_container, orient=tk.VERTICAL)
    log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    log_list = tk.Listbox(
        log_container,
        font=("Consolas", 14),
        height=8,
        exportselection=False,
        yscrollcommand=log_scroll.set,
    )
    apply_listbox_theme(log_list)
    log_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    log_scroll.config(command=log_list.yview)

    # Aktionen
    actions = ttk.Frame(app, padding=(16, 8), style="White.TFrame")
    actions.pack(fill=tk.X)

    ttk.Button(actions, text="Treffer löschen", bootstyle="danger", command=delete_selected).pack(
        side=tk.LEFT, padx=(0, 12)
    )
    ttk.Button(
        actions,
        text="Alle anzeigen",
        bootstyle="secondary",
        command=lambda: (search_var.set(""), run_search()),
    ).pack(side=tk.LEFT)

    # Initiale Daten anzeigen
    show_result_panel(True)
    display_packages(fetch_all_packages())
    update_counter_label()
    ensure_focus()

    # periodische Syncs starten
    app.after(2000, schedule_sync)

    # Suchfeld bei Fokusverlust sofort zurückholen (Scanner-Komfort)
    def refocus(_event: tk.Event) -> None:
        ensure_focus()

    app.bind_all("<FocusOut>", refocus, add="+")


if __name__ == "__main__":
    build_gui()
    app.mainloop()

