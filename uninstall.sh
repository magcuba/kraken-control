#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo 'Run: sudo bash uninstall.sh' >&2; exit 1; fi
systemctl disable --now kraken-control.service 2>/dev/null || true
rm -f -- /etc/systemd/system/kraken-control.service \
 /etc/systemd/system/kraken-control.service.d/90-profile.conf \
 /run/systemd/system/kraken-control.service.d/95-kraken-screen-preview.conf \
 /usr/local/bin/kraken-control \
 /usr/local/share/applications/io.github.magcuba.KrakenControl.desktop \
 /usr/local/share/icons/hicolor/scalable/apps/kraken-control.svg
for file in app.py backend.py dashboard.py monitor.py theme_editor.py theme_renderer.py cpu_display.py README.md LICENSE; do
 rm -f -- "/usr/local/lib/kraken-control/$file"
done
rmdir /usr/local/lib/kraken-control /etc/systemd/system/kraken-control.service.d 2>/dev/null || true
systemctl daemon-reload
if command -v update-desktop-database >/dev/null; then update-desktop-database /usr/local/share/applications; fi
echo 'Uninstalled. Personal themes/preferences and /var/lib/kraken-control were kept.'
echo 'The device may keep its last cooling settings while powered. This script does not reset fan or pump speeds.'
