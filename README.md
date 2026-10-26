# BOP Evolve

**Learning from Every Mistake. Improving Every Generation.**

An interactive prototype of the BOP Evolve employee-learning and service-quality dashboard: a **Dockerized server** (FastAPI + PostgreSQL + a simulated event stream) with a bilingual (English / Arabic, full RTL) React UI that runs **in the browser** or as a **cross-platform desktop app** (Electron — Windows, macOS, Linux).

> **Demo data only.** Every record is synthetic and clearly labelled. Mock sign-in is for local use. Do not connect this prototype to production systems, and never use its outputs to judge real employees. See [docs/governance.md](docs/governance.md).

---

## Contents

- [What's included](#whats-included)
- [One-click start on Windows](#one-click-start-on-windows)
- [Quick start (Docker)](#quick-start-docker)
- [Desktop app (Electron)](#desktop-app-electron)
- [Configuration screen](#configuration-screen)
- [Demo accounts](#demo-accounts)
- [Development](#development)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Prototype acceptance checklist](#prototype-acceptance-checklist)
- [Troubleshooting](#troubleshooting)

## What's included

| Area | Implementation |
|---|---|
| **Executive Overview** | Reviewed interactions, finding statuses, recurrence after follow-up, awareness distribution, action completion, G0–G5 distribution, weekly trend, pipeline/model health, last successful ingestion, worker heartbeat. Live refresh with last-updated / stale indicators. |
| **Findings Register** | Filter by status, service type, severity, org unit, dates, ID/pseudonym. Case detail with evidence pointers, applicable policy version, expected behaviour vs observed deviation, the control rule's matched conditions with the facts observed, rule/model output, confidence, limitations. |
| **"Was the employee aware?"** | Three separate views: the employee's own account (before/after feedback), reviewer assessment (policy clear? evidence supports? system issue?), demonstrated learning (comparable follow-up cases). |
| **Workflow** | Review decisions (confirm / confirm with amendment / uphold objection / dismiss), employee account & objection, corrective actions with owners, due dates and completion evidence. |
| **Workforce Development** (Chief HR Officer) | Every employee by department, region, branch and section: development stage, confirmed findings and repeats, the latest finding, corrective actions completed and overdue, the learning-from-findings rate, a 90-day repeat-risk outlook and open knowledge gaps. Drill down from bank to section. Each employee has a printable **Employee Development Report** (findings timeline with the review decision and the action taken by the manager or supervisor, occurrence by service type, knowledge gaps, outlook with the suggested development action and the model card). Views and prints are audited. See [docs/workforce.md](docs/workforce.md). |
| **Workplace policies** | Attendance, check-in / check-out, breaks and dress code against HR-01..HR-03, evaluated daily by the rules engine. Time KPIs (on-time check-in, breaks within allowance, lost hours per employee per month, attendance, punch completeness, dress-code compliance, a 0–100 adherence index) with drill-down from bank to section, weekly and weekday patterns, exceptions by rule and the reasons staff gave. Employees explain their exceptions; line managers excuse, confirm (with a light follow-up) or dismiss, one by one or in bulk, and record dress-code checks. See [docs/onboarding-and-workplace.md](docs/onboarding-and-workplace.md). |
| **Staff onboarding** (HR) | Brings 3,400+ staff from C-level to officers into the system: roster CSV import validated row by row, access derived from grade and department, invitation waves with one-time activation codes (hashed, expiring), and a five-step welcome journey (activate, language, tour, policy acknowledgement, 3-question check) followed in an onboarding funnel by department and grade, with AI-drafted reminders. |
| **AI assistant** (Groq, `openai/gpt-oss-20b`) | Drafts policy statements and control rules (validated by the rules engine), explains backtests, prepares review conversations, writes development summaries and workplace insights, and personalises onboarding, in English and Arabic. Pseudonymised inputs only; each feature can be switched off; every call is cached, logged and audited; the key lives only in `.env` or encrypted in System Configuration. See [docs/ai-assistant.md](docs/ai-assistant.md). |
| **Guided tour** | A **Guided tour** button in the top bar walks any user through the sections they can open — 24 steps for the Chief HR Officer, from the executive overview through a real case file to the employee report — with a gliding spotlight, fading cards, Previous / Next / Finish and arrow-key navigation (mirrored in Arabic). It starts by itself on the Chief HR Officer's first sign-in. |
| **Staff Development** | Versioned, evidence-gated development stages (G0 Baseline → G5 Sustained performance); live evaluation with indicator breakdown, coverage, gaps and warnings; immutable version history; approval of proposed versions; coaching sessions; dated timeline. |
| **Branch & Unit Performance** | Department / region / branch / section aggregates with privacy suppression and systemic-cause share. |
| **Intervention Planning** | Aggregate, illustrative recurrence estimates per intervention with 90 % intervals, sample sizes and limitations. Employee-level estimates disabled behind an approval gate. |
| **Management Reports** | Quality trends, common issues, repeat-after-coaching, training effectiveness, awaiting response, overdue actions, data quality, model performance — with CSV export. |
| **Policies & Control Rules** | Policy versions and control rules written as plain-language conditions on each case's procedural facts. Draft → submit → approve under the four-eyes principle; backtest on history with a 30/90-day forecast and comparison with the version in force; early-warning indicators that are monitored but never raise findings. Active rules drive the worker. See [docs/rules-engine.md](docs/rules-engine.md). |
| **How BOP Evolve Works** | Interactive map of the nine-step control loop with animated cases, live volumes, exits (quarantined, compliant, dismissed), a guided tour of one example case, safeguards and a glossary. See [docs/how-it-works.md](docs/how-it-works.md). |
| **Data & Model Operations** | Seven simulated pipelines covering every state (`HEALTHY`, `RUNNING`, `DEGRADED`, `FAILED`, `PAUSED`, `STALE`), run history, quarantine, pause/resume; model registry across every lifecycle state with drift / override / latency. |
| **System Configuration** (System Administrator) | Database connections with test, schema validation against the BOP Evolve model, a table-by-table diff with the exact SQL, and transactional apply gated by both the app permission and the database account's privileges. Runtime settings (default language, session length, privacy thresholds, retention, learning-method weights and thresholds) and pipeline schedules/SLAs. Data / AI Ops can view and run checks; only a System Administrator can change anything. |
| **Administration** | Users and scoped role grants, role-permission matrix, source systems (approved/enabled), audit log, configuration. |
| **Security** | Server-side RBAC with organisational scopes, server-side sessions (logout revokes), audit events with redaction, request IDs, production guard against mock auth, hardened Electron shell. |

Every page opens with a short brief (purpose, what you will see, what it tells you, who uses it) that each user can collapse. All wording follows one corporate glossary in English and Arabic: [docs/glossary.md](docs/glossary.md).

The sign-in screen has an ambient data-flow animation (raw fragments are validated, merged and condensed into answers); it honours the OS "reduce motion" setting.

Architecture: [docs/architecture.md](docs/architecture.md) · Onboarding & workplace policies: [docs/onboarding-and-workplace.md](docs/onboarding-and-workplace.md) · AI assistant: [docs/ai-assistant.md](docs/ai-assistant.md) · How it works: [docs/how-it-works.md](docs/how-it-works.md) · Rules engine: [docs/rules-engine.md](docs/rules-engine.md) · Glossary: [docs/glossary.md](docs/glossary.md) · Workforce & outlook model: [docs/workforce.md](docs/workforce.md) · Schema: [docs/data-dictionary.md](docs/data-dictionary.md)

## One-click start on Windows

Download or clone the repository, then **double-click `bop-evolve.bat`** (or run it from a terminal). It needs only what ships with Windows 10 / 11; everything else is checked and installed for you.

1. **Checks the computer:** Windows version (10 build 19041+ or 11), 64-bit CPU, memory, free disk, hardware virtualization, WSL 2, winget and internet access.
2. **Installs what is missing**, after asking: WSL 2 and Docker Desktop via `winget` (approve the administrator prompts), then starts Docker Desktop and waits for it. It also switches Docker to Linux containers if needed.
3. **Prepares the environment:** creates `.env` from `.env.example` with a random local session secret, fixes Windows line endings in the container entrypoint, and uses `.certs\extra-ca.pem` automatically if you work behind a TLS-inspecting proxy.
4. **Picks free ports automatically.** The web UI prefers 8080 and the API 8000. If a port is busy (another app, or a port Windows reserves for Hyper-V/WSL), the next free one is chosen and saved as `WEB_PORT` / `API_PORT` in `.env`, so the address stays the same next time. If BOP Evolve is already running, its current ports are kept.
5. **Builds only what changed and starts** the containers, waits until every service is healthy, prints the URLs and demo sign-in, and opens the browser. Each image is rebuilt only when its source files change (tracked in `.bop-build-state.json`), and inside a rebuild Docker reinstalls Python or npm packages only when `requirements.txt` or `package-lock.json` changed.

| Command | What it does |
|---|---|
| `bop-evolve.bat` | Everything above (same as `start`). |
| `bop-evolve.bat desktop` | Same, then installs Node.js LTS if needed and opens the Electron desktop app, already pointed at the detected API port. |
| `bop-evolve.bat update` | Gets the latest `main` from GitHub, rebuilds only the images whose source changed and restarts. Demo data and `.env` are kept. See [Updating](#updating-to-the-latest-version). |
| `bop-evolve.bat check` | Only runs the system and Docker checks. Installs nothing. |
| `bop-evolve.bat status` | Shows container status and the URLs in use. |
| `bop-evolve.bat logs` | Follows the container logs (Ctrl+C to stop). |
| `bop-evolve.bat stop` | Stops BOP Evolve and keeps the demo data. |
| `bop-evolve.bat reset` | Deletes the demo data and starts fresh (asks first). |
| `bop-evolve.bat help` | Shows all commands and options. |

Options: `--yes` answers install/reset questions automatically, `--no-browser` skips opening the browser, `--no-pause` closes the window without waiting for a key press, `--rebuild` rebuilds every image regardless, `--branch=NAME` updates from another branch. Each run is logged to `bop-evolve-launcher.log`.

**First-time Docker install:** Windows may ask you to restart after WSL 2 / Docker Desktop are installed, and Docker Desktop asks you to accept its terms on first start. Do that, then run `bop-evolve.bat` again; it continues where it left off. On locked-down PCs where PowerShell runs in Constrained Language Mode, the launcher stops with an explanation; ask IT for an exception or use the manual steps below.

### Updating to the latest version

Run **`bop-evolve.bat update`** in the project folder. It:

1. Makes sure Git is installed (installs Git for Windows with winget after asking). The repository is private: the first time, a GitHub sign-in window opens; sign in with an account that has access.
2. **First run in a folder downloaded as a ZIP:** connects the folder to GitHub in place. Files that are replaced, or that no longer exist in the new version, are moved to `.bop-backup\<date-time>\` first; `.env`, `.certs` and the demo data are kept.
3. **Later runs:** downloads only the new commits and fast-forwards to `main`, then lists what changed. If you edited project files, it offers to set them aside with `git stash` (restore with `git stash pop`); nothing is overwritten silently.
4. Rebuilds only the images whose source changed (an update that touches only the backend rebuilds only the backend), restarts the containers that need it, and applies database migrations automatically. With nothing new, it finishes in seconds.

**Getting the update command the first time:** copies of BOP Evolve from before this command existed have an older `bop-evolve.bat`. Replace it once with the current one: on GitHub, open `bop-evolve.bat` on the `main` branch and choose *Download raw file*, save it over the old file, then run `bop-evolve.bat update`. (Alternatively download the repository ZIP once more and copy `bop-evolve.bat` from it.)

## Quick start (Docker)

**Prerequisites:** Docker Desktop (Windows / macOS) or Docker Engine + Compose v2 (Linux). Nothing else is required to run the server.

```bash
git clone https://github.com/abuwalid1998/BOP-Evolve.git
cd BOP-Evolve
docker compose up -d --build        # or: npm run up
```

The first start builds the images, runs database migrations and seeds ~9 months of synthetic history (about a minute).

| URL | What |
|---|---|
| http://localhost:8080 | Web UI |
| http://localhost:8000/docs | Interactive API docs (OpenAPI) |
| http://localhost:8000/api/health | Health check |

Useful commands (identical on PowerShell, cmd, bash and zsh):

```bash
docker compose ps                    # service status (all four should be "healthy")
docker compose logs -f worker        # watch the simulated event stream
docker compose down                  # stop (keeps data)
docker compose down -v               # stop and delete data; next "up" reseeds fresh demo data
```

The same commands exist as npm scripts in the root `package.json` (`npm run up | down | reset | logs | ps | dev`) if you prefer.

## Desktop app (Electron)

The desktop app is a thin, hardened client: it bundles the same UI and connects to the Docker server. Data, access control and audit stay on the server.

### Run it from source

Requires Node.js 22 LTS and a running server (`docker compose up -d`).

```bash
npm --prefix frontend ci
npm --prefix desktop ci
npm --prefix desktop start           # builds the UI and opens the desktop window
```

On the sign-in screen, the **Server** panel shows and lets you change the server URL (default `http://localhost:8000`) and test the connection. You can also preset it with `BOP_EVOLVE_SERVER_URL`. The setting is saved per user.

For UI development with hot reload inside the desktop window: `npm --prefix desktop run dev`.

### Build installers

Build on the target OS (installers cannot be reliably cross-built):

| OS | Command | Output in `desktop/release/` |
|---|---|---|
| Windows | `npm --prefix desktop run dist:win` | `BOP-Evolve-<ver>-win-x64.exe` installer, `…-win-x64-portable.exe`, arm64 installer |
| macOS | `npm --prefix desktop run dist:mac` | `.dmg` and `.zip` for Intel (x64) and Apple silicon (arm64) |
| Linux | `npm --prefix desktop run dist:linux` | `.AppImage` (x64, arm64) and `.deb` (x64) |

The **Desktop installers** GitHub Actions workflow (`.github/workflows/desktop.yml`) builds all three on Windows, macOS and Ubuntu runners — run it from the *Actions* tab or push a `v*` tag, then download the artifacts. Builds are unsigned; production distribution must be code-signed with the bank's certificates.

## Configuration screen

**System Configuration** (System Administrator; read-only for Data / AI Ops) has five tabs.

- **Database**
  - The current application database is always listed. Add PostgreSQL connection profiles (host, port, database, user, SSL mode, schema).
  - Passwords are stored encrypted with `CONFIG_SECRET_KEY`, or referenced from a server environment variable named `BOP_DBPASS_<NAME>`. They are never sent back to the browser.
  - **Test connection** shows latency, server version, SSL and the account's privileges (superuser, can create tables, which tables it owns, read-only).
  - **Check schema** compares the database with what BOP Evolve expects. You get a status (valid / differences / empty), the migration revision, a per-table list of differences, unmanaged tables, and the changes needed to make it valid, each with its SQL.
  - **Changes** are grouped into three categories:
    - **Safe** (create table / column / index / constraint): applied by default.
    - **Risky** (type or nullability changes): only with an explicit opt-in.
    - **Destructive** (drops): reported, never applied.
  - Each change is marked *Allowed* or *Blocked* based on the database account's privileges.
  - **Apply** requires the `config.manage` permission, an unchanged plan since the check, and typing the database name. It runs everything in one transaction (nothing changes if any statement fails). When the schema ends up valid it records the migration revision so automatic upgrades keep working. Every test, check and apply is audited.
- **Application settings**: change values at runtime, see the default for each, and reset to default. Learning-method weights must add up to 1; changing the method creates a new method version so existing history stays traceable.
- **AI assistant**: where the Groq key comes from (masked), save a key encrypted or remove it, **Test connection**, model, reasoning effort, master and per-feature switches, and 30-day usage. See [docs/ai-assistant.md](docs/ai-assistant.md).
- **Pipelines**: schedule, freshness SLA, owner and runbook per pipeline.
- **Environment**: read-only server settings (environment, sign-in mode, database, expected revision, encryption-key and host-allowlist status).

Server settings for this screen:

| Variable | Purpose |
|---|---|
| `CONFIG_SECRET_KEY` | Fernet key (32 url-safe base64 bytes) that encrypts saved connection passwords. Required in production; in development it is derived from `JWT_SECRET`. `bop-evolve.bat` generates one for new installs. |
| `DB_CONNECTION_ALLOWED_HOSTS` | Comma-separated hosts the screen may connect to, wildcards allowed (`db.internal,*.bank.local`). Empty means any host in development and **none** in production. |
| `BOP_DBPASS_<NAME>` | Optional per-connection password supplied by the secrets manager instead of storing it. |

## Demo accounts

All demo accounts share the local-only password **`Evolve#Demo2026`** (configurable with `DEMO_PASSWORD`), except the Chief HR Officer account `hr.chief`, which uses **`123`** (configurable with `HR_CHIEF_PASSWORD`). These are demonstration passwords only; mock sign-in is refused when `APP_ENV=production`. The sign-in screen lists them; click one to fill the username.

| Username | Role | Scope | Sees |
|---|---|---|---|
| `superadmin` | System Administrator | Global | Everything, including administration and audit. |
| `dept.head` | Department Head | Retail Banking | Aggregates, insights, reports, scenarios (no case content). |
| `regional.north` | Regional Manager | North Region | Region cases, learning, insights, scenarios. |
| `branch.n01` | Branch Manager | North Branch 01 | Branch cases, reviews, actions, approvals, coaching, restricted evidence. |
| `section.n01` | Section Manager | N01 Tellers | Section cases, reviews, actions. |
| `lead.br-n01-tel` | Team Lead | N01 Tellers | Team cases, actions, coaching; decides workplace exceptions and records dress-code checks. |
| `employee.demo` | Customer Service Employee | Own records (`E-1001`) | Own findings, respond/dispute, own actions, own learning profile, own attendance record (explain exceptions). |
| `hr.ld` | HR / L&D | Global | Learning profiles, approvals, coaching, insights, reports, scenarios. |
| `risk.compliance` | Risk / Compliance / Audit | Global | Cases, reviews, restricted evidence, reports, model health, audit log. |
| `data.ops` | Data / AI / IT Ops | Global | Pipeline & model health and ops reports only — no case content. |
| `analyst` | Analyst (read-only) | Global | Aggregated insights and reports only. |
| `hr.chief` | Chief HR Officer | Global | Workforce development for every employee, printable employee reports, case files, staff development, insights, reports, scenarios. **Own demo password: `123`** (`HR_CHIEF_PASSWORD`). |
| `ops.policy` | Policy Owner | Global | Drafts and approves policy versions and control rules (never their own); aggregates and reports. |

**New staff** from a roster import have no password until they activate: on the sign-in screen choose **First time? Activate your account** and enter the employee number, the one-time code from the wave's CSV and a new password. Try it: as `hr.chief`, open **Staff onboarding**, download the sample roster (3,400 fictional people), import it, create a wave and launch it.

A good walkthrough: sign in as `employee.demo` and respond to a pending finding → sign in as `branch.n01`, review it and agree an action → back as the employee, complete the action with an evidence reference → as `branch.n01` or `hr.ld`, open the profile and re-evaluate / approve the proposed version. Watch each step appear in the audit log as `superadmin`.

## Development

Hot reload for API and UI inside Docker:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
# UI (Vite):  http://localhost:5173     API: http://localhost:8000     Postgres: 127.0.0.1:5432
```

Without Docker (Python 3.12+, Node 22):

```bash
# Backend — uses SQLite or any PostgreSQL in DATABASE_URL
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell
# source .venv/bin/activate         # macOS / Linux
pip install -r requirements-dev.txt
$env:DATABASE_URL="sqlite:///./dev.db"   # PowerShell
# export DATABASE_URL=sqlite:///./dev.db # macOS / Linux
alembic upgrade head
python -m app.seed.seed_mock_data
uvicorn app.main:app --reload       # API on :8000
python -m app.pipeline.worker       # (second terminal) simulated event stream

# Frontend
cd frontend
npm ci
npm run dev                         # http://localhost:5173, proxies /api to :8000
```

Tests and checks:

```bash
cd backend && pytest -q                                    # SQLite
TEST_DATABASE_URL=postgresql://user:pass@host/db pytest -q # PostgreSQL
ruff check . && ruff format --check app tests
cd frontend && npm run build                               # type-check + production build
```

CI (`.github/workflows/ci.yml`) runs lint, tests on SQLite and PostgreSQL, migration drift check, the frontend build and a Docker Compose smoke test.

## Configuration

Copy `.env.example` to `.env` to override defaults (Compose reads it automatically). Values are local-only; production secrets must come from the bank's approved secrets manager.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` refuses mock auth, demo mode and the default JWT secret. |
| `DEMO_MODE` | `true` | Enables demo account listing and the synthetic-data header. |
| `AUTH_MODE` | `mock` | Prototype login. Production must integrate SSO/OIDC. |
| `JWT_SECRET` | dev value | Session token signing key. |
| `DEMO_PASSWORD` | `Evolve#Demo2026` | Password set on seeded demo accounts. |
| `SESSION_TTL_MINUTES` | `480` | Server-side session expiry. |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | local values | Database container. |
| `API_PORT` / `WEB_PORT` | `8000` / `8080` | Host ports. |
| `WORKER_TICK_SECONDS` | `10` | Simulated stream tick. |
| `SEED_ON_START` | `true` | Seed synthetic data when the database is empty. |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:8080` | Extra browser origins (`app://bop-evolve` for the desktop app is always allowed). |
| `PRIVACY_MIN_GROUP_EMPLOYEES` / `PRIVACY_MIN_GROUP_CASES` | `3` / `10` | Default insight suppression thresholds (adjustable at runtime on the Configuration screen). |
| `CONFIG_SECRET_KEY` / `DB_CONNECTION_ALLOWED_HOSTS` | empty | See [Configuration screen](#configuration-screen). |
| `GROQ_API_KEY` | empty | Groq key for the AI assistant. Put it in `.env` only (never commit it), or store it encrypted from System Configuration › AI assistant. The backend must reach `api.groq.com`. |
| `GROQ_MODEL` / `GROQ_BASE_URL` / `AI_TIMEOUT_SECONDS` | `openai/gpt-oss-20b` / Groq / `45` | Model, OpenAI-compatible endpoint and timeout. |

**Behind a TLS-inspecting corporate proxy?** If image builds fail with `CERTIFICATE_VERIFY_FAILED`, copy your proxy's CA bundle (PEM) to `.certs/extra-ca.pem` (git-ignored) and build with:

```bash
EXTRA_CA_CERT=./.certs/extra-ca.pem docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d --build
```

The bundle is only mounted during the build and is not stored in the images.

## Branding

The Bank of Palestine logo is used in the web UI sidebar and sign-in screen (`frontend/src/assets/logo.png`), the browser favicon (`frontend/public/favicon.png`/`.ico`) and the desktop app and installer icon (`desktop/build/icon.png`, 1024 × 1024). To change it, replace those three files and rebuild (`docker compose up -d --build`; `npm --prefix desktop run dist`).

## Project layout

```text
BOP-Evolve/
├── bop-evolve.bat               # one-click Windows launcher (checks, installs, picks ports, runs)
├── docker-compose.yml           # db · backend · worker · frontend
├── docker-compose.dev.yml       # hot-reload overrides
├── docker-compose.proxy.yml     # optional corporate-proxy CA for builds
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI routers (auth, dashboard, cases, learning, insights, ops, reports, admin)
│   │   ├── models/              # SQLAlchemy models
│   │   ├── services/            # rbac, scoping, learning (G0–Gx), simulation, audit, security
│   │   ├── pipeline/            # synthetic catalogue, simulated worker, healthcheck
│   │   ├── seed/                # synthetic demo data
│   │   └── main.py
│   ├── migrations/              # Alembic
│   ├── tests/
│   └── Dockerfile
├── frontend/                    # React + TypeScript (Vite), EN/AR with RTL
│   ├── src/{pages,components,i18n,api,auth,hooks,styles}
│   ├── nginx.conf
│   └── Dockerfile
├── desktop/                     # Electron shell + electron-builder config
│   ├── src/{main,preload,settings}.js
│   └── electron-builder.yml
├── docs/                        # architecture, how it works, rules engine, glossary, data dictionary, governance
└── .github/workflows/           # CI and desktop installer builds
```

## Prototype acceptance checklist

- [x] Mock data is clearly labelled on every screen (persistent banner, API header, CSV exports).
- [x] Login and logout work; logout revokes the server session; demo credentials are not real.
- [x] System Administrator and least-privilege role views are represented (13 roles with scopes).
- [x] Arabic/English switching works, including full RTL layout.
- [x] Each finding shows rationale, policy reference and version, and the rule conditions it met.
- [x] Control rules and policy versions follow a four-eyes approval workflow and can be backtested before approval.
- [x] Every page carries a bilingual brief, and all terms follow one glossary.
- [x] Employee awareness is captured separately from reviewer judgement and demonstrated learning.
- [x] Learning history shows dated, evidence-backed G0–Gx versions (append-only, approval required).
- [x] Corrective actions have owners, deadlines, status and completion evidence.
- [x] Pipeline and model statuses show last-updated timestamps.
- [x] Failed and stale pipelines generate visible warnings.
- [x] Simulation outputs are marked illustrative and include limitations.
- [x] Audit events record sensitive workflow changes and access.
- [x] No real customer or employee data is present.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/bin/sh^M: bad interpreter` in a container (Windows) | The repo enforces LF via `.gitattributes`; re-clone, or run `git config core.autocrlf false` and `git checkout -- .`. |
| Port 8080 / 8000 already in use | `bop-evolve.bat` picks free ports automatically. Manually: set `WEB_PORT` / `API_PORT` in `.env` and update the desktop server URL if you change `API_PORT`. |
| `bop-evolve.bat` window closes or shows errors | Read `bop-evolve-launcher.log` next to it, or run `bop-evolve.bat check` from a terminal. |
| Desktop app says "Cannot reach the BOP Evolve server" | Check `docker compose ps`, then use **Server → Test connection** on the sign-in screen. |
| Overview shows "Simulated event stream: Not reporting" | `docker compose logs worker`; restart with `docker compose restart worker`. |
| Want fresh demo data | `docker compose down -v && docker compose up -d`. |

## License

[MIT](LICENSE)
