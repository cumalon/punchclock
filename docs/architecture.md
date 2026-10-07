# Architecture

## Runtime

The reference terminal runs the complete application locally:

```text
Chromium kiosk
     |
     | HTTP :8000
     v
Waitress
     |
     v
Flask / TimeClockPi
     |
     v
SQLite
```

The same HTTP service can be reached over Ethernet by an administration computer. Internet access is not required for clocking.

## Main components

- `app.py`: Flask routes, API and identification-token lifecycle.
- `timeclock/database.py`: SQLite schema, persistence, validation and punch business rules.
- `wsgi.py`: production WSGI entry point; initializes the database and exposes the Flask app to Waitress.
- `terminal_startup.py`: initializes the database and records the terminal `startup` event. It is run once by a dedicated systemd oneshot service during OS boot.
- `templates/` and `static/`: kiosk and administration web interfaces. `static/default-logo.svg` is the generic repository branding; installation-specific branding is persistent data outside Git.
- `tests/`: API and database tests.

## Identification and punching

A valid PIN is resolved to an employee by `/api/identify`. The API returns a short-lived random identification token. A punch request sends this token rather than trusting an employee ID supplied by the browser.

The token currently has a 60-second lifetime. A successful punch consumes it. An invalid or expired token is rejected. If a punch sequence requires incident confirmation, the token is retained and its expiry refreshed so the employee can confirm or cancel.

Employee identity and credentials are separate. Changing a PIN does not change the employee identity or historical punches.

Employee PIN identification is rate-limited globally in the current single-process terminal backend. Five failed employee-PIN attempts within 60 seconds trigger a 60-second lockout. The limiter is checked before credential lookup so a locked request does not reveal whether a supplied PIN is valid; the kiosk also hides the keypad briefly when reporting the lockout. This protection is intentionally in-memory and matches the current single-terminal deployment.

## Punch incidents

The core checks the employee's punch sequence and retains enough cross-day context to detect an earlier entry that has no following exit. Examples that require confirmation are a first recorded action that is a clock-out, two consecutive clock-ins or clock-outs on the same day, and a new clock-in when the employee's previous recorded punch is an entry from an earlier day.

A clock-out after midnight is allowed as the normal counterpart of an entry from the previous day, so legitimate night shifts are not treated as incidents merely because the calendar date changed. The system never invents an automatic clock-out or closes a work period at midnight.

The contemplated sequence situations are:

| Previous recorded punch | New punch | Result |
| --- | --- | --- |
| No previous punch | Entry | Normal |
| No previous punch | Exit | Incident: exit without a preceding entry |
| Entry, same day | Entry | Incident: consecutive entries |
| Entry, same day | Exit | Normal |
| Exit, same day | Entry | Normal |
| Exit, same day | Exit | Incident: consecutive exits |
| Entry, earlier day | Exit | Normal: permits a shift crossing midnight |
| Entry, earlier day | Entry | Incident: earlier entry has no following exit |
| Exit, earlier day | Entry | Normal |
| Exit, earlier day | Exit | Incident: consecutive exits |

In other words, the normal sequence remains `entry -> exit -> entry -> exit` across calendar boundaries. The date is used to describe the anomaly more precisely, not to reset the employee's punch sequence.

Confirmed anomalous punches are stored with `incident=1` and a descriptive note. Normal punches use `incident=0` and an empty note. The system records punches and obvious sequence anomalies; it does not infer how many hours were actually worked or whether an unusually long interval is valid. Such questions require human review rather than automatic alteration of punch history.

An administrator can mark an incident as reviewed and attach an observation. A reviewed incident can later be reopened if the review was mistaken; reopening requires a reason. Every review/reopen action is appended to the incident-review history with the administrator identity and timestamp. The original incident flag and note are never cleared or rewritten.

## Punch traceability

A recorded punch is never deleted, whether it is normal or contains an incident. The administration API deliberately provides no punch deletion operation.

If a recorded punch needs to be corrected, the effective employee, timestamp or punch type can be changed only through the correction workflow. Each correction stores the previous and new values, the administrator who made the change, the correction timestamp and a mandatory reason. This preserves the history of what was originally recorded and of subsequent administrative changes.

Incident review follows the same non-destructive principle: resolving or reviewing an incident adds audit information without removing the original incident. Punch records are therefore persistent and administrative changes are audited rather than destructive.

Punch timestamps remain stored and displayed as timezone-aware Europe/Madrid ISO timestamps. Chronological decisions and listings do not rely on lexical ordering of those local strings: SQLite connections register a normalization function that converts timestamps to UTC sort keys. This keeps ordering correct through the repeated local hour at the autumn DST transition while preserving the existing local representation and cross-day punch semantics. Administrator-corrected timestamps are normalized back to Europe/Madrid before storage, and correction history uses the same UTC-based chronological ordering.

## Persistence

SQLite is stored locally. Development defaults to `data/timeclock.db`, while the validated production service sets `TIMECLOCKPI_DATA_DIR=/var/lib/timeclockpi`; `data/` is intentionally not versioned in Git.

Every application connection enables SQLite foreign-key enforcement. Before schema initialization or migrations are applied to an existing database, `init_database()` runs `PRAGMA quick_check`. A failed check aborts startup. Corrupt production data is not automatically recreated, repaired or replaced.

The backend is supervised by systemd. Automatic restart remains enabled for transient failures, but repeated startup failures are rate-limited so a persistent problem such as database corruption does not produce an endless restart loop. Severe database/storage recovery is deliberately a technician CLI operation; the web administration is not a degraded-mode recovery environment.

The validated deployment uses SQLite `journal_mode=delete` with `synchronous=FULL`. The operating system uses an ext4 root filesystem with journaling and boot-time filesystem repair. The system journal remains volatile by distribution policy. TimeClockPi has separate bounded persistent technical logging under `/var/log/timeclockpi`, with rotation and compression, rather than enabling persistent storage for the complete system journal.

The main tables are employees, credentials, punches, terminal events, settings, administrator accounts, punch corrections and incident-review history.

Custom branding follows the same separation between source and installation data. The generic logo is versioned at `static/default-logo.svg`; an optional PNG/JPEG custom logo is stored at `$TIMECLOCKPI_DATA_DIR/branding/custom-logo`. `timeclock/branding.py` validates uploaded image structure and size, avoids following symlinks when reading the live logo, and uses same-directory temporary files, `fsync` and atomic replacement for durable updates.

## Network boundary

Ethernet is the v1 network interface, but application semantics do not depend on Ethernet. A future Wi-Fi interface can expose the same API. Clocking itself must continue to work without a network connection.

## Not yet implemented

RFID and fingerprint identification, Wi-Fi configuration, central synchronization, multiple-terminal coordination and a central server remain future capabilities.


## Administrator authentication

Administrator access is separate from employee identification. Employee PINs are used only for recording punches and do not grant access to the administration interface.

The administration interface uses dedicated administrator usernames and passwords. Multiple administrator accounts are supported so audited actions can be attributed to the person who performed them. Passwords are stored as Werkzeug password hashes rather than plaintext. After a successful login, Flask maintains an authenticated browser session; administrative pages and API endpoints verify that session server-side.

The browser session is represented by an HTTP-only cookie with SameSite protection and a limited lifetime. The Flask signing key is generated locally on the terminal and stored outside version control. State-changing administration requests are protected with a per-session CSRF token. Logging out clears the authenticated session. Each administrative API request also revalidates that the administrator is still active and that the account `updated_at` value matches the value captured at login. Password changes/resets, administrator-PIN changes and account activation changes therefore invalidate previously issued administrator sessions.

The initial administrator account is deliberately created locally on the terminal rather than supplied as a default credential. Privileged account management (creating, listing, enabling/disabling accounts and resetting forgotten passwords) is also performed locally through `admin_user.py`, not through the web interface. An authenticated web administrator may change only their own password; a successful change clears the current session and requires a new login.

This authentication layer protects application-level administration. It does not replace operating-system security, database file permissions, network security, or physical security of the terminal. In particular, deployments using plain HTTP should be limited to a trusted network; HTTPS is required if administrator credentials or session cookies must be protected against network interception on an untrusted network.


## USB punch export

The kiosk USB workflow is deliberately limited to punch export; backup and restore are administration/recovery operations rather than kiosk functions.

When a managed USB device is available, the kiosk asks for the administrator's individual six-digit PIN. Administrator PINs are stored as password hashes and are separate from both employee punch PINs and administrator web passwords. A successful PIN check produces a short-lived, one-use export token. Five failed PIN checks within the current rate-limit window cause a one-minute lockout.

The export is written as a UTF-8 CSV with BOM through a temporary `.partial` file, flushed with `fsync`, atomically renamed, then read back as bytes and compared with the expected content before safe eject. Export authorization failures, successful authorizations and completed exports are recorded as terminal events; the PIN itself is never logged.

Managed USB filesystems are mounted with `nosuid,nodev,noexec`. Safe eject and restore use narrowly scoped root helpers exposed through explicit sudoers entries rather than generic passwordless sudo access.

## Backup and restore

`backup.py` provides backup creation, verification and non-destructive restore preparation. The web process stages restore input under `/run/timeclockpi/restore`; the restricted root helper treats that location as untrusted, accepts only the expected regular files without following symlinks, snapshots them into the root-owned private journal at `/var/lib/timeclockpi-restore`, and verifies the database before replacing live data.

Before replacing the database or session key, the helper durably records rollback material and transaction state in the private journal. Live replacement uses same-filesystem atomic operations plus file/directory synchronization. The rollback journal remains until the restored backend passes its health check. A failed health check restores the previous state, and a power loss while a restore is pending is handled at the next boot by `timeclockpi-restore-recover.service` before the startup-event service or backend is allowed to run. The recovery service also normalizes ownership and mode of the production data directory when no restore transaction is pending.

Current-format backup manifests also describe branding state explicitly. Restore preparation stages either a custom-logo set action or a clear action in persistent application data. Branding finalization is deferred while the privileged database restore reports `running`: only a committed restore may apply the staged branding action, while rollback preserves the previous logo. The pending action is persistent across power loss and is correlated with a nonce stored in the restored database. Legacy backups without branding metadata preserve the installation's existing logo.

The restore launcher uses a transient systemd unit so the privileged restore process survives stopping `timeclockpi.service`. The application user has sudo access to the narrow launcher, not directly to the apply helper. Restore HTTP endpoints live under `/api/admin/usb/...` and therefore require an authenticated administrator session and CSRF protection for state-changing requests. The web administration provides the complete backup/restore workflow: creating and listing USB backups, preparing a selected restore, explicit final confirmation, applying the restore and reporting its result.
