#!/bin/sh
set -eu

APP_USER="punch"
APP_HOME="/home/$APP_USER"
APP_DIR="$APP_HOME/timeclockpi"
DATA_DIR="/var/lib/timeclockpi"
LOG_DIR="/var/log/timeclockpi"
TMPFILES_SOURCE="$APP_DIR/deploy/tmpfiles/timeclockpi.conf"
TMPFILES_TARGET="/etc/tmpfiles.d/timeclockpi.conf"
SYSTEMD_DIR="/etc/systemd/system"
HELPER_DIR="/usr/local/lib/timeclockpi"
UDEV_DIR="/etc/udev/rules.d"
LOGROTATE_DIR="/etc/logrotate.d"
SUDOERS_DIR="/etc/sudoers.d"
GETTY_OVERRIDE_DIR="/etc/systemd/system/getty@tty1.service.d"

if [ "$(id -u)" -ne 0 ]; then
    echo "Aquest instal·lador s'ha d'executar com a root" >&2
    exit 1
fi

if ! id "$APP_USER" >/dev/null 2>&1; then
    echo "No existeix l'usuari requerit: $APP_USER" >&2
    echo "Crea'l abans d'executar aquest instal·lador." >&2
    exit 1
fi

if [ ! -d "$APP_DIR/.git" ] || [ ! -f "$APP_DIR/requirements.txt" ]; then
    echo "No s'ha trobat un checkout de TimeClockPi a $APP_DIR" >&2
    exit 1
fi

install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$DATA_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$LOG_DIR"
install -d -o root -g root -m 0700 /var/lib/timeclockpi-restore

if [ ! -f "$TMPFILES_SOURCE" ]; then
    echo "No s'ha trobat $TMPFILES_SOURCE" >&2
    exit 1
fi

install -o root -g root -m 0644 "$TMPFILES_SOURCE" "$TMPFILES_TARGET"
systemd-tmpfiles --create "$TMPFILES_TARGET"

apt-get update
apt-get install -y python3 python3-venv labwc wlr-randr chromium

if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    runuser -u "$APP_USER" -- python3 -m venv "$APP_DIR/.venv"
fi

runuser -u "$APP_USER" -- "$APP_DIR/.venv/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$APP_HOME/.config"
install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$APP_HOME/.config/labwc"
install -o "$APP_USER" -g "$APP_USER" -m 0644 "$APP_DIR/deploy/kiosk/profile" "$APP_HOME/.profile"
install -o "$APP_USER" -g "$APP_USER" -m 0755 "$APP_DIR/deploy/kiosk/labwc-autostart" "$APP_HOME/.config/labwc/autostart"
install -o "$APP_USER" -g "$APP_USER" -m 0644 "$APP_DIR/deploy/kiosk/labwc-rc.xml" "$APP_HOME/.config/labwc/rc.xml"
install -d -o root -g root -m 0755 "$GETTY_OVERRIDE_DIR"
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/getty@tty1.service.d/autologin.conf" "$GETTY_OVERRIDE_DIR/autologin.conf"

install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/timeclockpi.service" "$SYSTEMD_DIR/timeclockpi.service"
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/timeclockpi-startup.service" "$SYSTEMD_DIR/timeclockpi-startup.service"
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/timeclockpi-restore-recover.service" "$SYSTEMD_DIR/timeclockpi-restore-recover.service"
systemctl daemon-reload
systemctl enable timeclockpi-restore-recover.service timeclockpi-startup.service timeclockpi.service

install -d -o root -g root -m 0755 "$HELPER_DIR"
install -o root -g root -m 0755 "$APP_DIR/scripts/timeclockpi-usb-mount" "$HELPER_DIR/timeclockpi-usb-mount"
install -o root -g root -m 0755 "$APP_DIR/scripts/timeclockpi-usb-unmount" "$HELPER_DIR/timeclockpi-usb-unmount"
install -o root -g root -m 0755 "$APP_DIR/scripts/timeclockpi-usb-eject" "$HELPER_DIR/timeclockpi-usb-eject"
install -o root -g root -m 0755 "$APP_DIR/scripts/timeclockpi-restore-apply" "$HELPER_DIR/timeclockpi-restore-apply"
install -o root -g root -m 0755 "$APP_DIR/scripts/timeclockpi-restore-launch" "$HELPER_DIR/timeclockpi-restore-launch"
install -d -o root -g root -m 0755 /mnt/timeclockpi-usb
install -o root -g root -m 0644 "$APP_DIR/deploy/systemd/timeclockpi-usb@.service" "$SYSTEMD_DIR/timeclockpi-usb@.service"
install -o root -g root -m 0644 "$APP_DIR/deploy/udev/99-timeclockpi-usb.rules" "$UDEV_DIR/99-timeclockpi-usb.rules"
install -o root -g root -m 0644 "$APP_DIR/deploy/logrotate/timeclockpi" "$LOGROTATE_DIR/timeclockpi"
install -o root -g root -m 0440 "$APP_DIR/deploy/sudoers/timeclockpi-restore-apply" "$SUDOERS_DIR/timeclockpi"
visudo -cf "$SUDOERS_DIR/timeclockpi"
systemctl daemon-reload
udevadm control --reload-rules

echo "Base del deployment preparada."
echo "Checkout: $APP_DIR"
echo "Dades persistents: $DATA_DIR"
echo "Logs persistents: $LOG_DIR"
echo "Serveis systemd instal·lats i habilitats."
echo "USB, restore, sudoers i rotació de logs instal·lats."
