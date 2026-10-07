# TimeClockPi

TimeClockPi is a standalone, extensible time-clock system designed initially for Raspberry Pi-based touchscreen terminals.

## Goals

- Work fully offline; networking must never be required to clock in or out.
- Touch-first kiosk interface for employees.
- Modular identification methods. The first implementation uses PINs; other methods can be added later without changing the core.
- Local SQLite storage.
- Web administration over the local network.
- Safe USB punch export plus backup/recovery infrastructure.
- Installation-local custom branding with a generic repository default.
- Simple, robust boot and recovery on appliance-style hardware.

## Version 1 scope

- Raspberry Pi OS on Raspberry Pi 2.
- Touchscreen kiosk UI.
- Employee management.
- PIN identification module.
- Clock-in / clock-out records.
- SQLite database.
- Visual and audible confirmation.
- Authenticated administrative web UI over Ethernet.
- Audited punch correction and incident review history.
- CSV export.
- Automatic application startup and restart.
- Touchscreen USB punch export authorized by an individual administrator PIN.

## Architecture

The core owns employees, credentials, clock events, configuration, persistence and business rules. Identification is provided through a small module interface: a module resolves its credential to an internal employee identity, while the core remains independent of the physical identification method.

Employee identity is independent from credentials. Changing a PIN must not change an employee's identity or history. Clock events record the identification method used.

The touchscreen UI and the administrative web UI use the same backend/API. Network interfaces are transport details: Ethernet is used in v1; Wi-Fi can be configured later without changing application semantics.

## Future capabilities (not implemented in v1)

Possible future modules or services include RFID, fingerprint identification, Wi-Fi configuration, automatic synchronization, multiple terminals and a central server. No placeholder directories are created for unimplemented features.

## Design principles

1. Offline-first.
2. Hardware-independent core.
3. Modular identification.
4. SQLite as the local source of truth.
5. API boundary between UI and core.
6. Minimal dependencies suitable for Raspberry Pi 2.
7. Safe administration separated from employee clocking credentials.
8. Non-destructive punch history: corrections and incident reviews are audited rather than deleted.

## Hardware target

The initial deployment target is a Raspberry Pi 2 Model B with a Raspberry Pi Display V1.1 touchscreen, installed in a repurposed time-clock enclosure. The software should avoid unnecessary coupling to that enclosure so it can be reused on other Raspberry Pi hardware.

## Status

The reference terminal is running the core v1 application on Raspberry Pi OS with Chromium kiosk mode, Waitress, Flask and SQLite. Automatic service/browser recovery, PIN identification, punch recording and incident confirmation have been validated on the terminal.

The administration interface now includes authenticated administrator sessions, CSRF-protected mutations, employee management, punch filtering, CSV exports, audited punch correction, reversible incident review with history, terminal settings, self-service password changes and individual six-digit administrator PINs. Administrator sessions are revalidated against the current account state and are invalidated after credential changes or account deactivation. Privileged administrator-account creation, password reset and enable/disable operations remain intentionally local terminal commands rather than web functions.

The reference terminal also has a validated USB workflow for exporting punch data from the kiosk. Export requires an administrator PIN, uses a short-lived one-use authorization token, rate-limits failed PIN attempts, verifies the CSV after writing, safely ejects the device and records authorization/failure/completion events without storing the PIN. USB media are mounted with `nosuid,nodev,noexec`.

Backup creation, verification and restore/rollback are available through the authenticated web administration. Backups also carry explicit branding state: a current-format backup can restore a custom logo or intentionally return the installation to the generic default, while legacy backups leave the installation's current logo unchanged. The production workflow has been validated end to end with real USB backups for both custom-logo and no-custom-logo states.

The repository contains only the generic `static/default-logo.svg`. An administrator can upload or remove an installation-specific PNG or JPEG logo from Web Admin. The custom file is stored under `TIMECLOCKPI_DATA_DIR/branding/`, outside Git, so source updates and reinstalls do not replace installation branding.

The initial production deployment now uses the `punch` account, a Git checkout at `/home/punch/timeclockpi`, persistent data under `/var/lib/timeclockpi`, bounded technical logging and versioned systemd/kiosk/USB deployment files. Full kiosk boot, startup-event recording, USB punch export and web backup/restore have been validated on the reference terminal. Remaining production-robustness work includes operational update/reinstall procedures, time validation, peripheral-error handling and evaluation of controlled local maintenance access.
