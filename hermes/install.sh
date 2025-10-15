#!/usr/bin/env bash
set -e

echo "[INFO] Installiere Hermes GUI-Service..."

# Root werden
if [ "$(id -u)" -ne 0 ]; then
  echo "[INFO] Bitte mit sudo ausführen"
  exit 1
fi

cd /root/aralbruehl
git pull
# Service stoppen und entfernen, falls vorhanden
systemctl stop hermes-gui.service 2>/dev/null || true
systemctl disable hermes-gui.service 2>/dev/null || true
rm -f /etc/systemd/system/hermes-gui.service

# Zielverzeichnis neu anlegen
rm -rf /opt/hermes
mkdir -p /opt/hermes

# Alle Dateien aus aktuellem Repo-Ordner kopieren
cp -r . /opt/hermes

# Service-Datei verschieben
mv /opt/hermes/hermes-gui.service /etc/systemd/system/hermes-gui.service

# Berechtigungen
chmod -R 755 /opt/hermes
chown -R pi:pi /opt/hermes

# Service aktivieren
systemctl daemon-reload
systemctl enable hermes-gui.service
systemctl start hermes-gui.service

echo "[OK] Hermes GUI-Service wurde erfolgreich installiert und gestartet."
