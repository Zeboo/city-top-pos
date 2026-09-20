# Top City POS build and deployment

## Local browser version

Install dependencies and start the web POS:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.web:app --reload
```

Open `http://127.0.0.1:8000` in a browser. The default seeded accounts are:

- Owner: `owner` / `owner123`
- Cashier: `cashier` / `cashier123`

Change these credentials before sharing the system publicly.

## Production image

The production image contains only the FastAPI server dependencies; the
PySide desktop application and PyInstaller are intentionally excluded.

```powershell
docker build -t top-city-pos .
docker run --rm -p 8000:8000 `
  -e SESSION_SECRET=replace-with-a-long-random-value `
  top-city-pos
```

Open `http://127.0.0.1:8000/health` to verify the container. A local container
without `DATABASE_URL` uses disposable SQLite storage. Use PostgreSQL in
production.

## First Railway setup

1. Push this repository to GitHub and create an empty Railway project.
2. Add a PostgreSQL service to that project.
3. Add an empty application service. The GitHub Actions pipeline uploads the
   application, so do not also enable GitHub auto-deploys for this service.
4. In the application service, set these variables:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
SESSION_SECRET=<long-random-secret>
RAILWAY_HEALTHCHECK_TIMEOUT_SEC=300
```

5. In the application service settings, set the health-check path to `/health`.
6. Generate a public domain under the service's Networking settings.

The Docker command listens on Railway's injected `PORT`. PostgreSQL tables are
created when the application starts. Existing local SQLite data is not copied
to PostgreSQL automatically; export/import it before going live if historical
data must be preserved.

## GitHub Actions deployment pipeline

The workflow in `.github/workflows/railway-deploy.yml` validates Python and
JavaScript, smoke-tests `/health`, and builds the Docker image on every pull
request. A successful push to `main` then deploys the same source to Railway
and waits for the deployment result.

Create a Railway **project token** for the production environment, then add
these GitHub repository secrets under **Settings > Secrets and variables >
Actions**:

```text
RAILWAY_TOKEN=<production project token>
RAILWAY_SERVICE_ID=<application service ID or exact service name>
```

The Railway project token belongs only in GitHub secrets. Do not add it to a
file or to Railway service variables. You can also start the workflow manually
from GitHub's Actions page.

## Windows desktop executable

Run `build_windows.bat` on Windows. The result is:

```text
dist\TopCityPOS.exe
```

Copy the complete `dist` folder or the executable to the shop computer. The desktop app keeps its local SQLite database under its `data` directory.

## Live Windows client (shared data across computers)

Open `dist\TopCityPOSLive\TopCityPOSLive.exe`. On the first launch, enter the
HTTPS address of your deployed POS, for example `https://your-pos.example.com`.
Use **Server address** in the toolbar to change it later. Sign in with a user
from that server. All connected computers see the same server database.

Copy the **entire `TopCityPOSLive` folder**, including `_internal`, to each
Windows 64-bit computer. Python does not need to be installed. The live client
requires a reachable server and internet (or a local network connection to a
LAN server). It does not synchronize the offline app's local database.

For a LAN server, run `python -m uvicorn app.web:app --host 0.0.0.0 --port 8000`
on the server computer, then enter `http://SERVER-LAN-IP:8000` in each client.
Keep that server running and allow its port through your firewall.

The existing `TopCityPOS.exe` is the separate offline application. The new
`TopCityPOSLive.exe` embeds the web interface and supports receipt printing.
`build_windows.bat` rebuilds both applications.

The owner System tab downloads a portable JSON snapshot of all database tables,
including credentials in hashed form. Store backups privately. This is a logical
backup, not a SQLite `.db` file; there is no in-app restore operation.

This update does not publish a server or migrate existing shop data. Configure
hosting, `DATABASE_URL`, and a strong `SESSION_SECRET` before public use.

## Verification

`tests/check_web.py` checks a running test server at `127.0.0.1:8765`. Start that
server with `DATABASE_URL` pointing to a disposable SQLite database, then run
`python tests/check_web.py`. Never point this test at the shop database: it creates
test orders, guests and users. JavaScript syntax can be checked with
`node --check app/web/app.js` and `node --check app/web/pos.js`.
