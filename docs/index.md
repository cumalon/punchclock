# TimeClockPi — Developer documentation

TimeClockPi is an offline-first time-clock application for Raspberry Pi touchscreen terminals.

This documentation describes the current implementation, development workflow, deployment on the reference terminal, and the decisions already validated on hardware.

## Current status

The current build runs on a Raspberry Pi 2 with Raspberry Pi OS Lite, Chromium in a Wayland/labwc kiosk, a Flask application served by Waitress, and SQLite local storage.

Implemented and validated:

- PIN identification with short-lived authorization tokens.
- Clock-in and clock-out, including explicit confirmation of anomalous sequences.
- Employee administration and terminal settings.
- Punch and terminal-event history plus CSV exports.
- Automatic boot and recovery of backend and kiosk.
- A terminal startup event recorded once per OS boot.
- Waitress WSGI deployment managed by systemd.
- USB punch export from the kiosk with individual administrator PIN authorization, failed-attempt throttling, write verification and safe eject.
- Web-admin USB backup and restore, including archive verification, explicit confirmation, backend health checking and automatic rollback on failed health checks.
- Administrator sessions invalidated when the account is disabled or its credentials change.
- Production layout using `punch`, `/home/punch/timeclockpi` and `/var/lib/timeclockpi`, with persistent bounded technical logging.

For a new terminal, follow the [clean installation procedure](deployment.md#clean-installation-on-a-new-raspberry-pi). See also [Architecture](architecture.md), [Development](development.md), [Deployment](deployment.md), and [Operations](operations.md).

## v1 principles

The terminal must remain usable offline. SQLite is the local source of truth. Employee identity is independent from credentials, and identification methods are kept separate from the core business logic. PIN is the only identification method implemented now; RFID and fingerprint are future possibilities, not current modules.
