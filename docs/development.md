# Development

## Python environment

The project uses a virtual environment at `.venv`.

Runtime dependencies are in `requirements.txt`. Development dependencies are in `requirements-dev.txt`, which includes the runtime set and adds pytest tooling.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Alternatively activate it:

```bash
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Tests

```bash
pytest
```

The test suite covers employee lifecycle and validation, PIN identification, token authorization, forged employee-ID rejection, normal and incident punch sequences, history filters, CSV export, settings, public kiosk settings, terminal events, administrator authentication, CSRF protection, password management, audited punch corrections, incident review/reopening and local administrator-account controls.

The suite should be run after each change with `pytest -q`. The exact test count is intentionally not documented here because it changes as coverage grows.

## Running the application manually

TimeClockPi can be run without the production systemd services while developing.

Activate the virtual environment from the repository root:

```bash
source .venv/bin/activate
```

Then start Flask's built-in development server:

```bash
python app.py
```

`app.py` initializes the database and starts Flask on port 8000. Leave that process running while using the application.

Open the kiosk application in a browser at:

```text
http://127.0.0.1:8000/
```

For example, if Chromium is already available in the graphical session, it can be pointed at that address. The browser is only the client: Flask is the process serving the HTML, static files and API during this development workflow.

To stop the development server, return to its terminal and press `Ctrl+C`.

### Development server vs production server

Flask includes a convenient HTTP development server, which is what `python app.py` starts. It is useful for development and manual testing but is not the server used by an installed TimeClockPi terminal.

In production, Waitress is the WSGI HTTP server. It imports the Flask application through `wsgi.py` and serves the same application/API:

```bash
waitress-serve --listen=0.0.0.0:8000 --threads=2 wsgi:app
```

So Flask remains the web application framework in both cases. What changes is the HTTP server in front of the Flask application: Flask's built-in server for development, Waitress for production.

The production terminal starts Waitress automatically through systemd; developers do not need those production services merely to run the application manually.

## Dependency policy

`requirements.txt` is the minimal runtime dependency set for an installed terminal. `requirements-dev.txt` adds tools needed to develop and test the application. Waitress is a runtime dependency because the deployed terminal serves the Flask application through it.
