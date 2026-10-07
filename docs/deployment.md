# Reference terminal deployment

This page records the deployment that has been validated on the reference Raspberry Pi 2 terminal.

## Platform

- Raspberry Pi 2 Model B.
- Raspberry Pi OS Lite 32-bit.
- Python 3.13.
- Europe/Madrid timezone.
- labwc Wayland compositor.
- `wlr-randr` for the DSI output transform.
- Chromium using native Wayland.
- Waitress serving Flask on port 8000.
- SQLite local database.

The validated production layout uses the login-capable kiosk account `punch`, the Git checkout at `/home/punch/timeclockpi`, persistent application data at `/var/lib/timeclockpi`, persistent technical logs at `/var/log/timeclockpi`, runtime state at `/run/timeclockpi`, and managed removable media at `/mnt/timeclockpi-usb`. The versioned deployment files under `deploy/` are the reference configuration.

## Backend systemd service

`/etc/systemd/system/timeclockpi.service`:

```ini
[Unit]
Description=TimeClockPi backend
After=local-fs.target timeclockpi-restore-recover.service timeclockpi-startup.service
Requires=timeclockpi-restore-recover.service
Wants=network.target

[Service]
Type=simple
User=punch
Environment=TIMECLOCKPI_DATA_DIR=/var/lib/timeclockpi
WorkingDirectory=/home/punch/timeclockpi
ExecStart=/home/punch/timeclockpi/.venv/bin/waitress-serve --listen=0.0.0.0:8000 --threads=2 wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Apply changes with:

```bash
sudo systemctl daemon-reload
sudo systemctl enable timeclockpi.service
sudo systemctl restart timeclockpi.service
```

The service has been validated to restart automatically after its Waitress process is killed.

## Startup event service

Backend restarts must not be recorded as terminal boots. A separate oneshot unit records one startup event per OS boot.

`/etc/systemd/system/timeclockpi-startup.service`:

```ini
[Unit]
Description=TimeClockPi terminal startup event
After=local-fs.target timeclockpi-restore-recover.service
Before=timeclockpi.service

[Service]
Type=oneshot
User=punch
Environment=TIMECLOCKPI_DATA_DIR=/var/lib/timeclockpi
WorkingDirectory=/home/punch/timeclockpi
ExecStart=/home/punch/timeclockpi/.venv/bin/python /home/punch/timeclockpi/terminal_startup.py

[Install]
WantedBy=multi-user.target
```

After execution this service is expected to be `inactive (dead)` with a successful exit status. That is normal for a oneshot unit.

## Graphical kiosk startup

Console autologin is enabled on tty1. The kiosk user's `~/.profile` starts labwc only on the physical console:

```sh
if [ "$(tty)" = "/dev/tty1" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    exec labwc
fi
```

`~/.config/labwc/autostart`:

```sh
#!/bin/sh

WAYLAND_DISPLAY=wayland-0 wlr-randr --output DSI-1 --transform 90

LABWC_PID=$(pgrep -n -x labwc)

while kill -0 "$LABWC_PID" 2>/dev/null; do
    WAYLAND_DISPLAY=wayland-0 chromium --ozone-platform=wayland --kiosk --disable-save-password-bubble --disable-features=PasswordManagerOnboarding http://127.0.0.1:8000
    sleep 3
done
```

For the reference Raspberry Pi Display, labwc sees the panel as `DSI-1` at 800x480. The physical terminal is portrait, so the output is transformed 90 degrees by `wlr-randr`. The kernel command line keeps the mode as `video=DSI-1:800x480@60` without a `rotate=` parameter; output rotation belongs to the Wayland layer.

The reference touchscreen is reported as `10-0038 generic ft5x06 (79)`. Add `~/.config/labwc/rc.xml` so touch coordinates follow the rotated output:

```xml
<?xml version="1.0"?>
<labwc_config>
  <libinput>
    <device category="touch">
      <calibrationMatrix>0 -1 1 1 0 0</calibrationMatrix>
    </device>
  </libinput>
</labwc_config>
```

The 90-degree output transform and this calibration matrix have been validated together after a full reboot on the reference terminal.

Make it executable:

```bash
chmod +x ~/.config/labwc/autostart
```

This arrangement has been validated for Chromium recovery and for rebuilding the graphical chain after labwc exits, without leaving an orphaned Chromium supervisor.

## Installation-local branding

The repository ships only the generic `static/default-logo.svg`. An installation-specific logo is persistent application data, not source code: when configured it is stored as `$TIMECLOCKPI_DATA_DIR/branding/custom-logo` (therefore `/var/lib/timeclockpi/branding/custom-logo` on the reference deployment). Updating or reinstalling the Git checkout does not overwrite this file.

Web Admin accepts PNG or JPEG custom logos up to 1 MB and with dimensions no greater than 4096×4096 pixels. SVG is deliberately not accepted as an uploaded custom logo. Removing the custom logo makes the application serve the repository's generic default again.

The data directory and branding file must remain writable by the application account. No installation-specific logo should be copied into `static/` or committed to Git.

## Validation

Useful checks:

```bash
sudo systemctl status timeclockpi.service --no-pager
curl http://127.0.0.1:8000/api/settings
```

A healthy Waitress service reports that it is serving on `0.0.0.0:8000`.

## Restore recovery service and directories

The installer also installs and enables `timeclockpi-restore-recover.service`. At boot, the backend requires this service and is ordered after it; the recovery service is ordered before both the backend and startup-event service. Recovery writes a root-owned `boot-recovered` marker under `/run/timeclockpi-restore` only after it has completed successfully. The unit has `ConditionPathExists=!/run/timeclockpi-restore/boot-recovered`, so systemd skips the recovery helper on later backend restarts in the same boot instead of starting a second helper that could wait on the active restore's journal lock. `/run` is recreated on reboot, so recovery is required and runs again at the next boot. If a power loss interrupts a restore, recovery uses the durable transaction journal in `/var/lib/timeclockpi-restore` to return the database and session key to their pre-restore state before the backend starts.

The installer creates `/var/lib/timeclockpi-restore` as `root:root` mode `0700`, and tmpfiles creates `/run/timeclockpi-restore` as `root:root` mode `0755` for read-only restore status. The web application continues to stage restore input under the `punch`-writable `/run/timeclockpi/restore` tree; the privileged helper treats it as untrusted and copies only validated regular files into its private journal without following symlinks. Re-run `deploy/install.sh` when upgrading an existing terminal so the new recovery unit and protected directories are installed.
