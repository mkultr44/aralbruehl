#!/usr/bin/env bash
set -e


echo "[Installing Service]f"

# Root werden
if [ "$(id -u)" -ne 0 ]; then
  echo "[INFO] Bitte mit sudo ausführen"
  exit 1
fi

cd /root/aralbruehl
echo "git pull..."
git pull
echo "stopping services..."
systemctl stop hermes-gui.service 2>/dev/null || true
systemctl disable hermes-gui.service 2>/dev/null || true
rm -f /etc/systemd/system/hermes-gui.service

echo "creating directory..."
rm -rf /opt/hermes
mkdir -p /opt/hermes

echo "copying files..."
cp -r . /opt/hermes

echo "creating service..."
mv hermes-gui.service /etc/systemd/system/hermes-gui.service

echo "setting permissions..."
chmod -R 755 /opt/hermes
chown -R pi:pi /opt/hermes

echo "activating service..."
systemctl daemon-reload
systemctl enable hermes-gui.service
systemctl start hermes-gui.service

