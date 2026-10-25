# BOP Evolve

**Learning from Every Mistake. Improving Every Generation.**

An interactive prototype of the BOP Evolve employee-learning and service-quality dashboard: a **Dockerized server** (FastAPI + PostgreSQL + a simulated event stream) with a bilingual (English / Arabic, full RTL) React UI that runs **in the browser** or as a **cross-platform desktop app** (Electron — Windows, macOS, Linux).

> **Demo data only.** Every record is synthetic and clearly labelled. Mock sign-in is for local use. Do not connect this prototype to production systems, and never use its outputs to judge real employees. See [docs/governance.md](docs/governance.md).

---

## Contents

- [What's included](#whats-included)
- [Quick start (Docker)](#quick-start-docker)
- [Desktop app (Electron)](#desktop-app-electron)
- [Demo accounts](#demo-accounts)
- [Development](#development)
- [Configuration](#configuration)
- [Project layout](#project-layout)
- [Prototype acceptance checklist](#prototype-acceptance-checklist)
- [Troubleshooting](#troubleshooting)

## What's included

| Area | Implementation |
|---|---|
| **Overview** | Reviewed interactions, finding statuses, recurrence after follow-up, awareness distribution, action completion, G0–G5 distribution, weekly trend, pipeline/model health, last successful ingestion, worker heartbeat. Live refresh with last-updated / stale indicators. |
| **Mistake Explorer** | Filter by status, category, severity, org unit, dates, ID/pseudonym. Case detail with evidence pointers, applicable policy version, expected vs observed action, rule/model output, confidence, limitations. |
| **"Did the employee know?"** | Three separate states: self-reported awareness (before/after feedback), reviewer assessment (policy clear? evidence supports? system issue?), demonstrated learning (comparable follow-up cases). |
| **Workflow** | Reviewer decisions (confirm / amend / uphold dispute / dismiss), employee response & dispute, improvement actions with owners, due dates and completion evidence. |
| **Employee Learning** | Versioned, evidence-gated G0 → Gx profile; live evaluation with indicator breakdown, coverage, gaps and warnings; immutable version history; approval of proposed versions; coaching sessions; dated timeline. |
| **Team & Branch Insights** | Department / region / branch / section aggregates with privacy suppression and systemic-cause share. |
| **Future Scenarios** | Aggregate, illustrative recurrence estimates per intervention with 90 % intervals, sample sizes and limitations. Employee-level estimates disabled behind an approval gate. |
| **Reports** | Quality trends, common issues, repeat-after-coaching, training effectiveness, awaiting response, overdue actions, data quality, model performance — with CSV export. |
| **Pipeline & Model Health** | Seven simulated pipelines covering every state (`HEALTHY`, `RUNNING`, `DEGRADED`, `FAILED`, `PAUSED`, `STALE`), run history, quarantine, pause/resume; model registry across every lifecycle state with drift / override / latency. |
| **Administration** | Users and scoped role grants, role-permission matrix, policies & versioned rules, integrations (approved/enabled), audit log, configuration. |
| **Security** | Server-side RBAC with organisational scopes, server-side sessions (logout revokes), audit events with redaction, request IDs, production guard against mock auth, hardened Electron shell. |

Architecture details: [docs/architecture.md](docs/architecture.md) · Schema: [docs/data-dictionary.md](docs/data-dictionary.md)

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

## Demo accounts

All demo accounts share the local-only password **`Evolve#Demo2026`** (configurable with `DEMO_PASSWORD`). The sign-in screen lists them; click one to fill the username.

| Username | Role | Scope | Sees |
|---|---|---|---|
| `superadmin` | Super Admin | Global | Everything, including administration and audit. |
| `dept.head` | Department Head | Retail Banking | Aggregates, insights, reports, scenarios (no case content). |
| `regional.north` | Regional Manager | North Region | Region cases, learning, insights, scenarios. |
| `branch.n01` | Branch Manager | North Branch 01 | Branch cases, reviews, actions, approvals, coaching, restricted evidence. |
| `section.n01` | Section Manager | N01 Tellers | Section cases, reviews, actions. |
| `lead.br-n01-tel` | Team Lead | N01 Tellers | Team cases, actions, coaching. |
| `employee.demo` | Customer-facing Employee | Own records (`E-1001`) | Own findings, respond/dispute, own actions, own learning profile. |
| `hr.ld` | HR / L&D | Global | Learning profiles, approvals, coaching, insights, reports, scenarios. |
| `risk.compliance` | Risk / Compliance / Audit | Global | Cases, reviews, restricted evidence, reports, model health, audit log. |
| `data.ops` | Data / AI / IT Ops | Global | Pipeline & model health and ops reports only — no case content. |
| `analyst` | Read-only Analyst | Global | Aggregated insights and reports only. |

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
| `PRIVACY_MIN_GROUP_EMPLOYEES` / `PRIVACY_MIN_GROUP_CASES` | `3` / `10` | Insight suppression thresholds. |

**Behind a TLS-inspecting corporate proxy?** If image builds fail with `CERTIFICATE_VERIFY_FAILED`, copy your proxy's CA bundle (PEM) to `.certs/extra-ca.pem` (git-ignored) and build with:

```bash
EXTRA_CA_CERT=./.certs/extra-ca.pem docker compose -f docker-compose.yml -f docker-compose.proxy.yml up -d --build
```

The bundle is only mounted during the build and is not stored in the images.

## Project layout

```text
BOP-Evolve/
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
├── docs/                        # architecture, data dictionary, governance
└── .github/workflows/           # CI and desktop installer builds
```

## Prototype acceptance checklist

- [x] Mock data is clearly labelled on every screen (persistent banner, API header, CSV exports).
- [x] Login and logout work; logout revokes the server session; demo credentials are not real.
- [x] Super Admin and least-privilege role views are represented (11 roles with scopes).
- [x] Arabic/English switching works, including full RTL layout.
- [x] Each finding shows rationale, policy reference and version.
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
| Port 8080 / 8000 already in use | Set `WEB_PORT` / `API_PORT` in `.env`. Update the desktop server URL if you change `API_PORT`. |
| Desktop app says "Cannot reach the BOP Evolve server" | Check `docker compose ps`, then use **Server → Test connection** on the sign-in screen. |
| Overview shows "Simulated event stream: Not reporting" | `docker compose logs worker`; restart with `docker compose restart worker`. |
| Want fresh demo data | `docker compose down -v && docker compose up -d`. |

## License

[MIT](LICENSE)
