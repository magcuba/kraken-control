#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run: sudo bash install.sh' >&2
  exit 1
fi
kraken_source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
kraken_app_dir=/usr/local/lib/kraken-control
if systemctl is-active --quiet kraken-cpu.service; then
  echo 'An older kraken-cpu.service is running. Stop it before installing; two USB writers must not run together.' >&2
  echo 'To migrate: sudo systemctl disable --now kraken-cpu.service' >&2
  exit 1
fi
for dependency in /usr/bin/python3 /usr/bin/liquidctl /usr/bin/pkexec; do
  if [ ! -x "$dependency" ]; then
    echo "Missing $dependency. Install the dependencies listed in README.md first." >&2
    exit 1
  fi
done
/usr/bin/python3 -c "import gi, cairo, PIL, psutil; gi.require_version('Gtk','3.0'); from gi.repository import Gtk"
if systemctl is-active --quiet kraken-control.service; then
  systemctl stop kraken-control.service
  kraken_restart_service=yes
else
  kraken_restart_service=no
fi
install -d -m 755 "$kraken_app_dir" /usr/local/bin /usr/local/share/applications /usr/local/share/icons/hicolor/scalable/apps
for file in app.py backend.py dashboard.py monitor.py theme_editor.py theme_renderer.py cpu_display.py README.md LICENSE; do
  install -o root -g root -m 644 "$kraken_source_dir/$file" "$kraken_app_dir/$file"
done
cat > /usr/local/bin/kraken-control <<'LAUNCH'
#!/bin/sh
exec /usr/bin/python3 /usr/local/lib/kraken-control/app.py "$@"
LAUNCH
chmod 755 /usr/local/bin/kraken-control
install -o root -g root -m 644 "$kraken_source_dir/packaging/io.github.magcuba.KrakenControl.desktop" /usr/local/share/applications/io.github.magcuba.KrakenControl.desktop
install -o root -g root -m 644 "$kraken_source_dir/assets/kraken-control.svg" /usr/local/share/icons/hicolor/scalable/apps/kraken-control.svg
install -o root -g root -m 644 "$kraken_source_dir/packaging/kraken-control.service" /etc/systemd/system/kraken-control.service
systemctl daemon-reload
if command -v update-desktop-database >/dev/null; then update-desktop-database /usr/local/share/applications; fi
if [ "$kraken_restart_service" = yes ]; then systemctl start kraken-control.service; fi
echo 'Installed. Open Kraken Control from your application menu.'
echo 'A fresh installation does not start the LCD updater or enable it at boot. Apply a screen or save a startup profile in the app.'
