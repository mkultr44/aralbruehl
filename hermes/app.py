#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import csv
import io
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Sequence, Tuple, Any

import requests
from rapidfuzz import fuzz, process

from kivy.app import App
from kivy.lang import Builder
from kivy.properties import (
    StringProperty,
    BooleanProperty,
    NumericProperty,
    ListProperty,
    ObjectProperty,
)
from kivy.clock import Clock
from kivy.uix.modalview import ModalView
from kivy.core.window import Window

# --- Konstanten / Farben ---
ARAL_BLUE = "#0078D7"
ARAL_RED = "#D00000"
ARAL_GREEN = "#009F4D"
WHITE = "#FFFFFF"
TEXT_DARK = "#0A0A0A"

# Fenstergröße fix (Touch-Optimierung)
Window.size = (1280, 800)
Window.minimum_width, Window.minimum_height = 1280, 800
Window.maximum_width, Window.maximum_height = 1280, 800

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "paket.db")
CSV_URL = (
    "https://nextcloud.aralbruehl.de/public.php/dav/files/"
    "mJAaPjgBycC7d7y/hermes_final.csv"
)
SYNC_INTERVAL_SECONDS = 30

# --- Datenmodell / DB ---
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

# --- Directory Cache ---
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
        for row in rows if row["sendungsnr"]
    }
    directory_cache = cache
    directory_choices = list(cache.keys())

rebuild_directory_cache()

# --- CSV Sync ---
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
    try:
        r = requests.get(CSV_URL, timeout=15)
        if r.status_code == 200:
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
    except Exception as exc:
        App.get_running_app().log_async(f"CSV Sync Fehler: {exc}")
    return None

def sync_directory(entries: Sequence[Tuple[str, str]]) -> None:
    ts = datetime.now().isoformat(timespec="seconds")
    with DB_LOCK:
        conn.execute("DELETE FROM directory")
        conn.executemany(
            "INSERT INTO directory (sendungsnr, name, updated_at) VALUES (?, ?, ?)",
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
        App.get_running_app().log_async("CSV Sync: keine Daten erhalten")
        return
    sync_directory(entries)
    App.get_running_app().log_async(f"CSV Sync abgeschlossen ({len(entries)} Einträge)")

# --- Kivy App ---
class LogView(ModalView):
    pass

class HermesApp(App):
    title = "Paket-Zonen-Manager"
    zone_status = StringProperty("Suche aktiv")
    einbuchen_mode = BooleanProperty(False)
    active_zone = StringProperty("")
    session_counter = NumericProperty(0)
    counter_color = StringProperty(ARAL_RED)
    result_items = ListProperty([])       # List[dict(text=..., index=...)] for RecycleView
    result_rows = ListProperty([])        # List[dict(rowdata)]
    selected_index = NumericProperty(-1)
    show_warning = BooleanProperty(False)
    _warning_event = ObjectProperty(allownone=True)

    log_lines = ListProperty([])          # for overlay
    max_log_lines = 400

    def build(self):
        from kivy.lang import Builder
        root = Builder.load_file(os.path.join(os.path.dirname(__file__), "ui.kv"))
        self.root = root
        Clock.schedule_once(lambda dt: self._post_build(), 0.05)
        Clock.schedule_once(lambda dt: self.schedule_sync(), 2.0)
        return root

    def _post_build(self):
        self.update_counter_label()
        self.display_packages(self.fetch_all_packages())
        self.ensure_focus()

    # --- Logging ---
    def log(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        self.log_lines.insert(0, line)
        if len(self.log_lines) > self.max_log_lines:
            del self.log_lines[self.max_log_lines:]

    def log_async(self, msg: str) -> None:
        Clock.schedule_once(lambda dt: self.log(msg), 0)

    def open_log_overlay(self):
        view = LogView(size_hint=(0.9, 0.8), auto_dismiss=True)
        view.open()

    # --- Focus ---
    def ensure_focus(self):
        try:
            self.root.ids.scanner_input.focus = True
            self.root.ids.scanner_input.cursor = (len(self.root.ids.scanner_input.text), 0)
        except Exception:
            pass

    # --- UI Bindings ---
    def update_counter_label(self):
        self.root.ids.header_counter.ids.counter_value_label.text = str(self.session_counter)
        self.counter_color = ARAL_GREEN if self.session_counter > 0 else ARAL_RED

    def _reset_zone_colors(self):
        for zid in ("A","B","C","D","E_1","E_2","E_3","E_4","F"):
            btn = self.root.ids.get(f"zone_{zid}")
            if btn:
                btn.tone = "normal"

    def _highlight_zone(self, zone: str, color: str):
        zid = zone.replace("-", "_")
        btn = self.root.ids.get(f"zone_{zid}")
        if not btn:
            return
        btn.tone = "blue" if color == "blue" else "red"

    def refresh_zone_highlights(self, selected_zone: Optional[str] = None):
        self._reset_zone_colors()
        if self.einbuchen_mode and self.active_zone:
            self._highlight_zone(self.active_zone, "blue")
        if selected_zone:
            self._highlight_zone(selected_zone, "red")

    # --- Warning Blink ---
    def _blink_warning(self, *args):
        lbl = self.root.ids.zone_warning
        if not self.show_warning:
            lbl.opacity = 0
            return
        lbl.opacity = 1.0 if lbl.opacity == 0.2 else 0.2
        self._warning_event = Clock.schedule_once(self._blink_warning, 0.4)

    def hide_zone_warning(self):
        self.show_warning = False
        lbl = self.root.ids.zone_warning
        lbl.opacity = 0
        if self._warning_event is not None:
            try:
                self._warning_event.cancel()
            except Exception:
                pass
            self._warning_event = None

    def show_zone_warning_label(self):
        self.show_warning = True
        lbl = self.root.ids.zone_warning
        lbl.opacity = 1.0
        if self._warning_event is None:
            self._warning_event = Clock.schedule_once(self._blink_warning, 0.4)

    # --- Zone Handling ---
    def set_zone(self, zone: str):
        if not self.einbuchen_mode:
            return
        self.active_zone = zone
        self.hide_zone_warning()
        self.refresh_zone_highlights()
        self.zone_status = f"Aktive Zone: {self.active_zone}"
        self.log(f"Zone {self.active_zone} gewählt")
        self.ensure_focus()

    def toggle_einbuchen(self):
        self.einbuchen_mode = not self.einbuchen_mode
        self.active_zone = ""
        self.refresh_zone_highlights()
        self.hide_zone_warning()
        if self.einbuchen_mode:
            self.session_counter = 0
            self.zone_status = "Einbuchen aktiv – bitte Zone wählen"
            self.root.ids.einbuchen_btn.text = "Fertig"
            self.log("Einbuchen gestartet")
        else:
            self.session_counter = 0
            self.zone_status = "Suche aktiv"
            self.root.ids.einbuchen_btn.text = "Einbuchen"
            self.run_search()
            self.log("Einbuchen beendet")
        self.update_counter_label()
        self.ensure_focus()

    # --- Fuzzy / Matching ---
    def match_directory(self, sendungsnr: str) -> Tuple[Optional[str], Sequence[str], Optional[int]]:
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

    # --- Packages Ops ---
    def insert_package(self, sendungsnr: str, zone: str, name: Optional[str]) -> None:
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

    def fetch_all_packages(self) -> List[sqlite3.Row]:
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

    # --- Results / Search ---
    def populate_result_list(self, items: Sequence[Dict[str, Any]], empty_message: str):
        self.result_rows = []
        self.result_items = []
        if not items:
            self.result_items = [{"text": empty_message, "index": -1}]
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

            self.result_items.append({"text": label, "index": len(self.result_rows)})
            self.result_rows.append({"sendungsnr": sendungsnr, "zone": zone})

        if not self.result_rows and len(self.result_items) == 0:
            self.result_items = [{"text": empty_message, "index": -1}]

    def display_packages(self, rows: Sequence[sqlite3.Row]):
        self.populate_result_list([dict(r) for r in rows], empty_message="Keine Pakete vorhanden")

    def run_search(self):
        term = self.root.ids.scanner_input.text.strip()
        rows = self.fetch_all_packages()
        if not rows:
            self.populate_result_list([], empty_message="Keine Pakete vorhanden")
            return
        if not term:
            self.display_packages(rows)
            return

        choices: Dict[str, sqlite3.Row] = {}
        dataset: Dict[str, str] = {}
        for row in rows:
            key = row["sendungsnr"]
            choices[key] = row
            candidate = " ".join(part for part in (row["sendungsnr"], row["name"], row["zone"]) if part)
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
            self.populate_result_list([], empty_message="Kein Treffer")
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

        self.populate_result_list(sorted_rows, empty_message="Kein Treffer")

    # --- UI events ---
    def on_text_validate(self):  # Enter gedrückt
        value = self.root.ids.scanner_input.text.strip()
        if not value:
            if not self.einbuchen_mode:
                self.run_search()
            return

        if self.einbuchen_mode:
            if not self.active_zone:
                self.log("Zone auswählen, bevor eingebucht wird")
                self.show_zone_warning_label()
                self.ensure_focus()
                return
            name, matches, score = self.match_directory(value)
            self.insert_package(value, self.active_zone, name)
            self.session_counter += 1
            self.update_counter_label()
            log_msg = f"{value} → {self.active_zone}"
            if name:
                log_msg += f" ({name})"
            if score is not None:
                log_msg += f" [Score {score}]"
            elif matches:
                log_msg += " [Mehrfachtreffer]"
            self.log(log_msg)
            if matches and len(matches) > 1:
                self.log(f"Fuzzy Matches: {', '.join(matches)}")
            self.root.ids.scanner_input.text = ""
            self.ensure_focus()
            return

        self.run_search()

    def on_search_button(self):
        self.run_search()
        self.ensure_focus()

    def on_all_button(self):
        self.root.ids.scanner_input.text = ""
        self.run_search()
        self.ensure_focus()

    def on_delete_button(self):
        idx = self.selected_index
        if idx is None or idx < 0 or idx >= len(self.result_rows):
            return
        sendungsnr = self.result_rows[idx]["sendungsnr"]
        with DB_LOCK:
            conn.execute("DELETE FROM packages WHERE sendungsnr=?", (sendungsnr,))
            conn.commit()
        self.log(f"{sendungsnr} gelöscht")
        # refresh list
        self.run_search()
        self.refresh_zone_highlights(None)

    def on_result_select(self, idx: int):
        self.selected_index = idx
        if idx is None or idx < 0 or idx >= len(self.result_rows):
            self.refresh_zone_highlights(None)
            return
        zone = self.result_rows[idx].get("zone") or ""
        self.refresh_zone_highlights(zone if zone else None)

    # --- Sync scheduling ---
    def schedule_sync(self):
        def worker():
            perform_sync()
            Clock.schedule_once(lambda dt: self.schedule_sync(), SYNC_INTERVAL_SECONDS)
        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    HermesApp().run()

