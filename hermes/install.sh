#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "[ERROR] Bitte als root bzw. mit sudo ausführen." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_DIR="${PROJECT_ROOT}/hermes"
TARGET_DIR="/opt/hermes"
VENV_DIR="${TARGET_DIR}/venv"
SERVICE_PATH="/etc/systemd/system/hermes-gui.service"

TARGET_USER="${SUDO_USER:-${USER:-pi}}"
if ! id -u "${TARGET_USER}" >/dev/null 2>&1; then
  TARGET_USER="pi"
fi
if ! id -u "${TARGET_USER}" >/dev/null 2>&1; then
  TARGET_USER="root"
fi
TARGET_GROUP="$(id -gn "${TARGET_USER}" 2>/dev/null || echo "${TARGET_USER}")"
TARGET_HOME="$(eval echo "~${TARGET_USER}" 2>/dev/null || echo "/home/${TARGET_USER}")"

log() {
  printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

log "Installationsverzeichnis vorbereiten (${TARGET_DIR})"
systemctl stop hermes-gui.service >/dev/null 2>&1 || true
systemctl disable hermes-gui.service >/dev/null 2>&1 || true
mkdir -p "${TARGET_DIR}"
rm -rf "${TARGET_DIR:?}"/*
cp -a "${SOURCE_DIR}/." "${TARGET_DIR}/"

log "Python-Virtualenv prüfen"
if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

log "Python-Abhängigkeiten installieren"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${TARGET_DIR}/requirements.txt"

log "Dateirechte anpassen"
chown -R "${TARGET_USER}:${TARGET_GROUP}" "${TARGET_DIR}"
chmod -R 755 "${TARGET_DIR}"

log "Systemd-Service schreiben"
cat <<SERVICE > "${SERVICE_PATH}"
[Unit]
Description=Hermes Paketmanager GUI Autostart
After=graphical.target network-online.target
Wants=graphical.target

[Service]
Type=simple
User=${TARGET_USER}
Environment=DISPLAY=:0
Environment=XAUTHORITY=${TARGET_HOME}/.Xauthority
WorkingDirectory=${TARGET_DIR}
ExecStart=${VENV_DIR}/bin/python3 ${TARGET_DIR}/app.py --fullscreen
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical.target
SERVICE

log "Systemd neu laden und Dienst aktivieren"
systemctl daemon-reload
systemctl enable hermes-gui.service
systemctl restart hermes-gui.service

log "Installation abgeschlossen"
