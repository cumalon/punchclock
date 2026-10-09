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

## Clean installation on a new Raspberry Pi

The procedure below was validated on a second microSD card using Raspberry Pi OS Lite 32-bit (Debian 13 / Trixie), Python 3.13 and the public repository's initial release (`b1cd245`). The original reference terminal was not modified. Commands are shown for a separate system administrator account (for example, `joan`) and the dedicated kiosk account `punch`.

### 1. Prepare Raspberry Pi OS

Install Raspberry Pi OS Lite (32-bit) with Raspberry Pi Imager. Configure the hostname, timezone (`Europe/Madrid`), keyboard, network and SSH as appropriate. Create a normal system administrator account during OS setup, sign in as that account and ensure it can use `sudo`.

Install Git as the system administrator:

```sh
sudo apt update
sudo apt install git
```

The `punch` account is separate from this administrator account. Do **not** add `punch` to the `sudo` group: the installer is run by the administrator, while the application and kiosk run as `punch`.

### 2. Create the kiosk account

As the system administrator:

```sh
sudo adduser punch
```

Set the account password when prompted; optional account details may be left blank. The account must have a login-capable home directory at `/home/punch`.

### 3. Clone the application as `punch`

The repository is named `punchclock`, but the deployment files require the checkout directory to be named `timeclockpi`.

From the administrator session, run:

```sh
sudo -u punch -H git clone https://github.com/cumalon/punchclock.git /home/punch/timeclockpi
```

Verify the checkout:

```sh
sudo -u punch git -C /home/punch/timeclockpi status
sudo -u punch git -C /home/punch/timeclockpi log -1 --oneline
```

Do not clone into `/home/punch/punchclock` unless you then rename it to `/home/punch/timeclockpi`. Do not run the installer from a different checkout under the administrator's home directory.

### 4. Run the deployment installer

From the **system administrator** session (not as `punch`):

```sh
sudo /home/punch/timeclockpi/deploy/install.sh
```

The installer requires the `punch` account and checkout to exist. It creates the persistent data and log directories, installs Python and graphical dependencies, sets up the virtual environment, configures the kiosk, and installs/enables the systemd, USB, backup/restore and log-rotation integration. It runs `apt-get install -y` internally, so package installation does not request confirmation.

Check that the services are installed and enabled:

```sh
sudo systemctl status timeclockpi.service timeclockpi-startup.service timeclockpi-restore-recover.service --no-pager
```

Immediately after installation, the services may be `inactive (dead)`: the installer enables them but does not start them.

### 5. Reboot and check the terminal

```sh
sudo reboot
```

After reconnecting as the system administrator:

```sh
sudo systemctl status timeclockpi.service timeclockpi-startup.service timeclockpi-restore-recover.service --no-pager
curl http://127.0.0.1:8000/api/settings
```

The backend should be `active (running)`. The startup and restore-recovery units are one-shot services and can normally show `inactive (dead)` after successful execution; check their result if troubleshooting. Chromium should start automatically on the physical terminal and display the kiosk. The web application listens on port `8000`.

The display rotation and touch calibration below are validated for the reference DSI screen; other screens may need different output and input settings.

### 6. Create the first web administrator

The Linux account `punch` is **not** the web administrator. Create a separate application administrator using the installed virtual environment and persistent data directory:

```sh
sudo -u punch -H env TIMECLOCKPI_DATA_DIR=/var/lib/timeclockpi /home/punch/timeclockpi/.venv/bin/python /home/punch/timeclockpi/admin_user.py create admin
```

Enter and confirm the password interactively. Do not put it in the command line. Then sign in to the web administration from a browser on the trusted local network. The web administrator's username need not be `admin`.

### 7. Functional acceptance checks

On a fresh installation, verify these operations before putting the terminal into service:

1. Create a test employee in web administration.
2. Clock in and out at the physical kiosk; verify both records in web administration.
3. Submit an anomalous consecutive punch; verify incident detection and administrator review.
4. Export punch history as CSV and inspect the file.
5. Attach a USB drive, create a backup and verify it.
6. On a test installation, change a test record, restore the verified backup and confirm the original data returns.

These checks passed during the clean-install validation. They do not replace further hardware-specific or long-duration testing. Never test a restore against production data without an appropriate recovery plan.

### Installation notes

- Run `sudo` commands from the **system administrator** account. A command such as `sudo ./deploy/install.sh` issued by `punch` will fail if that account is correctly excluded from sudoers.
- For repository checks from the administrator account, use `git -C /home/punch/timeclockpi` rather than trying to pass `cd` directly to `sudo -u punch`.
- The installer currently assumes fixed paths and the account name `punch`; changing these requires coordinated changes to the deployment configuration.
- The system is designed to work offline for employee punches, but downloading packages and cloning the repository during initial installation require network access.
- Plain HTTP is used on the reference terminal. Restrict administrative access to a trusted network.

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
