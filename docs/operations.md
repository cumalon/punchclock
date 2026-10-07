# Operations and validated behavior

## Boot and recovery

The reference terminal has been tested for:

- automatic backend startup;
- one terminal `startup` event per OS boot;
- no additional startup event when only the backend service restarts;
- automatic Waitress restart through systemd;
- automatic Chromium restart;
- reconstruction of the kiosk graphical chain after labwc exits.

## Backend health

```bash
sudo systemctl status timeclockpi.service --no-pager
curl http://127.0.0.1:8000/api/settings
```

Stopping the backend does not necessarily remove the already-rendered kiosk page from the screen. The browser can still display cached/current HTML, but API actions such as PIN identification will report a connection error until the backend returns.

Employee PIN identification is protected by a temporary brute-force lockout. Five failed employee-PIN attempts within 60 seconds block identification for 60 seconds, including otherwise valid PINs during that interval. The kiosk reports the temporary limitation without revealing whether a submitted PIN exists. The limiter is in-memory in the current single-process terminal backend, so restarting the backend resets its state.

## Exports

Punch CSV columns are:

```text
Data;Hora;Treballador;Tipus;Metode;Incidencia
```

Normal punches leave the incident column empty. Confirmed anomalous punches export their descriptive incident note.

Terminal events have a separate CSV export.

Punch listings and latest-punch decisions use UTC-normalized chronological ordering while retaining Europe/Madrid timestamps for display and export. This avoids lexical misordering during the repeated local hour at the autumn daylight-saving transition. The same ordering rule applies to punch-correction history.

## Administration

The web administration interface requires a dedicated administrator account. Employee PINs never grant administrative access. Authenticated state-changing requests use CSRF protection.

Administrators can correct a punch but cannot delete it. Every correction requires a reason and preserves an audit record containing the previous and new values, administrator and timestamp. Incidents can be reviewed, annotated and reopened; all review-state changes remain in history.

The punch-history origin filter supports all records, a specific employee, or `Terminal` for technical terminal events only.

An administrator can change their own password from the web interface. Privileged administrator-account management is intentionally restricted to local terminal access:

```bash
python admin_user.py list
python admin_user.py create USERNAME
python admin_user.py reset-password USERNAME
python admin_user.py disable USERNAME
python admin_user.py enable USERNAME
```

Passwords are prompted interactively and are not passed on the command line. At least one administrator must remain active, so the local account-management command refuses to disable the last active administrator.

Administrator sessions are checked against the live administrator record on every administrative API request. Disabling an account or changing/resetting its credentials invalidates an already-open session on its next request.

Plain HTTP is currently used by the reference deployment. Administrative access should therefore remain on a trusted network; HTTPS is required when credentials and session cookies need protection from interception on an untrusted network.

## Kiosk USB punch export

USB on the kiosk is for punch export only. Backup and restore are not kiosk operations.

A detected USB device prompts for an individual six-digit administrator PIN. The PIN is masked on screen and is stored only as a hash in the database. A successful authorization is short-lived and single-use. Five failed PIN attempts trigger a one-minute temporary lockout.

A successful export:

1. writes `fitxatges-YYYYMMDD-HHMMSS.csv` through a temporary partial file;
2. flushes the file to storage;
3. reads the final file back and verifies its exact bytes;
4. records the completed export in `terminal_event`;
5. safely unmounts/ejects the managed USB device.

Terminal events also record failed PIN authorizations and successful export authorizations. The administrator PIN is never recorded.

## Backup and recovery

Backup archives are verified before restore preparation. The web process stages the selected files in `/run/timeclockpi/restore`, which is writable by `punch`; the root restore helper treats that tree as untrusted. It opens only the expected regular files without following symlinks, copies them into a root-owned private journal under `/var/lib/timeclockpi-restore`, and verifies the staged database before touching live data. The helper secures the live data directory while replacing files and gives the database and session key back to `punch` with their required modes before restarting the backend.

The helper durably records the prior database and session key before replacing either file, then uses same-filesystem atomic replacement and directory/file synchronization. It retains that rollback journal until the restored backend passes its health check. If the host loses power while a restore is pending, `timeclockpi-restore-recover.service` restores the previous data before the startup event or backend service can run. A failed health check also restores the prior data and reports `rollback`; a successful restore reports `success`.

The restore launcher runs the apply helper in a transient systemd unit so stopping the normal backend service does not kill the restore operation. Restore endpoints are under the authenticated `/api/admin/usb/...` API namespace. The web administration can create and verify backups on USB, list verified archives, prepare a selected restore, require an explicit final confirmation and report the restore/rollback result. The administrator's web workflow remains unchanged. Current-format manifests may include branding metadata while retaining compatibility with legacy backups that predate branding support.

The USB mount helper creates `/run/timeclockpi` as `punch:punch` while keeping the `usb-device` state file managed by root. This allows the web backend to stage restore data without making the backend systemd service own the shared runtime directory. A full OS reboot with the USB connected has been validated: the backend returns active, the USB remounts with `nosuid,nodev,noexec`, and `/run/timeclockpi/usb-device` is reconstructed with the actual device path.

## Database and storage recovery

Serious storage or database failures are maintenance operations and are intentionally handled from the command line rather than through a special recovery web interface. If the backend cannot start, the already-rendered kiosk page may remain visible, but API operations will fail.

### Diagnosis

Start by checking the backend and its recent service log:

```bash
sudo systemctl status timeclockpi.service --no-pager
sudo journalctl -u timeclockpi.service -n 100 --no-pager
```

A persistent startup failure is rate-limited by systemd: the backend may retry several times, but repeated failures are stopped instead of creating an endless restart loop. A database integrity failure is therefore expected to leave the service in a failed state for technician intervention.

Check the SQLite database without modifying it:

```bash
python - <<'PY'
import sqlite3

path = "/var/lib/timeclockpi/timeclock.db"
db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
print("quick_check:", db.execute("PRAGMA quick_check").fetchone()[0])
db.close()
PY
```

For a more exhaustive check, replace `quick_check` with `integrity_check`. An exception such as `file is not a database`, or a result other than `ok`, must be treated as database corruption. Do not initialize a replacement database over the damaged file.

Also check storage capacity and inode availability:

```bash
df -h /
df -i /
```

If storage or filesystem damage is suspected, inspect kernel messages for I/O, filesystem or MMC errors before changing application data.

### Recovery procedure

Recovery from a corrupt database should be performed by a technician:

1. Stop `timeclockpi.service` before manipulating the database.
2. Preserve the problematic database as evidence/recovery material. Do not overwrite or delete the only copy.
3. Locate a known-good TimeClockPi backup and verify it before applying it.
4. Restore using the project's recovery tooling rather than manually constructing a new database.
5. Verify the restored database with `PRAGMA integrity_check`.
6. Reset any systemd failed state if necessary, start the backend, and confirm that the service and local API are healthy.
7. Confirm normal kiosk operation before returning the terminal to service.

A database that fails integrity checks is never considered repaired merely because the service can be made to start. Automatic creation, destructive repair or silent replacement of a corrupt production database is deliberately avoided.

### Power-loss and filesystem behavior

The reference deployment uses an ext4 root filesystem with journaling and boot-time filesystem repair enabled. A physical abrupt-power-loss test was performed after a committed punch: on the following boot, ext4 performed orphan recovery, SQLite passed its integrity check, the committed punch remained present and the backend started automatically. This validates the tested recovery scenario, not immunity to arbitrary power loss during an SD-card write.

Application SQLite connections enable foreign-key enforcement. The validated deployment currently uses SQLite `journal_mode=delete` and `synchronous=FULL`; these settings are intentionally left unchanged while the current single-terminal workload remains appropriate for them.

The distribution's system journal remains volatile (`Storage=volatile`) to avoid making the complete system journal an additional persistent SD-card write workload. TimeClockPi writes persistent technical warnings and errors to `/var/log/timeclockpi/timeclockpi.log`; logrotate applies bounded weekly rotation and compression.

## Visual interface

The kiosk visual redesign has been validated on the physical reference terminal at its real display resolution and orientation. The validated flows include PIN entry, entry/exit selection, anomalous-punch incident confirmation, USB administrator-PIN authorization, invalid USB PIN feedback and successful USB export feedback.

The incident confirmation explicitly identifies the situation as a punch incident and visually distinguishes confirmation from cancellation. The web administration redesign has also been reviewed across punch consultation/export, employees, backups/restore, configuration and administrator login.

## Pending work

Production robustness is the current phase. The deployment now uses the `punch` account and production paths consistently across the backend, startup event, USB and restore helpers. Controlled reboot/shutdown and emergency local maintenance access remain production-robustness topics. Hardware identification and auxiliary hardware are postponed until after the initial production deployment.

Future work may include Wi-Fi, synchronization and multiple terminals.

## Custom logo

The repository contains only the generic `static/default-logo.svg`. From Web Admin → Configuration → *Custom logo*, an administrator can upload a PNG or JPEG logo up to 1 MB and 4096×4096 pixels. The custom logo is stored at `$TIMECLOCKPI_DATA_DIR/branding/custom-logo`, outside Git. Removing it returns the interface to the generic repository logo. SVG uploads are rejected.

Current-format backups record branding state explicitly in the manifest. A backup created with a custom logo includes that logo and restores it; a backup created without a custom logo records that state and removes any current custom logo when restored. Backups created before branding support have no branding marker and deliberately leave the installation's current logo unchanged.

Branding participates in restore commit/rollback semantics without giving the privileged restore helper control over the logo file. While restore status is `running`, application startup does not finalize the pending branding change. After a committed restore, the application applies the staged set/clear action; after rollback it preserves the previous logo. Pending state survives a power loss so boot recovery can resolve the database transaction before branding is finalized.

The physical reference terminal has been validated in both directions: restoring a backup that contains a custom logo restores that logo in Web Admin and the Chromium kiosk, and restoring a current-format backup that records no custom logo removes the existing custom logo and returns both interfaces to the generic default.
