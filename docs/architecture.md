# Architecture

BOP Evolve runs as a **server stack in Docker** plus **two interchangeable clients**: a web browser and an Electron desktop app. Both clients load the same React build. All data, access control and audit stay on the server.

```text
 ┌──────────────────────────┐      ┌──────────────────────────────┐
 │ Browser                  │      │ Electron desktop app         │
 │ http://localhost:8080    │      │ Windows · macOS · Linux      │
 │  (same-origin /api)      │      │ UI served from app://bop-evolve
 └────────────┬─────────────┘      └──────────────┬───────────────┘
              │ HTTPS/HTTP                         │ HTTP(S) to configured server URL (CORS-allowed origin)
 ┌────────────▼─────────────┐                      │
 │ frontend (nginx)         │                      │
 │ static UI + /api proxy   │                      │
 └────────────┬─────────────┘                      │
              │                                    │
 ┌────────────▼────────────────────────────────────▼─┐
 │ backend (FastAPI)  :8000                          │
 │ auth · RBAC/scope · workflow · learning · reports │
 │ audit events · request IDs                        │
 └────────────┬───────────────────────────┬──────────┘
              │                           │
 ┌────────────▼────────────┐   ┌──────────▼──────────────┐
 │ db (PostgreSQL 16)      │◄──┤ worker (simulated       │
 │ cases, findings, audit, │   │ connectors + rules)     │
 │ learning generations    │   │ heartbeat, pipeline/    │
 └─────────────────────────┘   │ model health            │
                               └─────────────────────────┘
```

## Containers

| Service | Image | Role |
|---|---|---|
| `db` | `postgres:16-alpine` | Operational store (named volume `db-data`). |
| `backend` | `backend/Dockerfile` | Runs `alembic upgrade head`, seeds synthetic data when empty, serves the API. |
| `worker` | same image, `worker` command | Simulated event stream: runs pipelines on schedule, validates/deduplicates/quarantines records, applies rules to create *potential* findings, updates pipeline/model health and its heartbeat. |
| `frontend` | `frontend/Dockerfile` | nginx serving the built UI and proxying `/api` to the backend. |

## Backend modules (`backend/app`)

| Module | Responsibility |
|---|---|
| `models/` | SQLAlchemy models for the logical schema in the specification (§11) plus `pipelines`, `quarantined_records`, `follow_up_evaluations`, `auth_sessions`, `service_heartbeats`. |
| `services/rbac.py` | Role catalogue, permission matrix, scope resolution (global / department / region / branch / section / self). |
| `services/scoping.py` | Turns a scope into SQL conditions so every list/detail endpoint filters on the server. |
| `services/learning.py` | Evidence-gated G0 → G5 evaluation, append-only versions, approval. |
| `services/simulation.py` | Aggregate, illustrative recurrence scenarios with Beta-posterior uncertainty. |
| `services/audit.py` | Audit events with metadata redaction. |
| `services/settings_store.py` | Typed runtime settings with defaults, validation and overrides in `app_settings`. |
| `services/dbschema.py` | Connection testing, privilege inspection, Alembic-based schema diff, safe/risky/destructive plan, transactional apply and revision stamping. |
| `services/secrets.py` | Encryption of stored connection passwords. |
| `api/` | Routers: `auth`, `dashboard`, `cases` (+findings/actions workflow), `learning`, `insights` (+simulations), `ops`, `reports`, `admin`, `config`. |
| `pipeline/` | Synthetic catalogue, simulated worker and its healthcheck. |
| `seed/` | Synthetic data generator (≈270 days of history). |

## Desktop client (`desktop/`)

* `src/main.js` registers a privileged `app://bop-evolve` scheme and serves the bundled UI from `renderer/` with path-traversal protection.
* Hardened `BrowserWindow`: `contextIsolation`, `sandbox`, no Node integration, navigation locked to the app origin, external links opened in the system browser, permission requests denied, no `<webview>`.
* `src/preload.js` exposes only `getServerUrl`, `setServerUrl` and `testServer`. The server URL is stored in the per-user app data folder (`settings.json`).
* The backend allows `app://bop-evolve` as a CORS origin.

## "Live" behaviour

The prototype polls (10–30 s, paused while the window is hidden) and every live view shows a last-updated timestamp and a stale warning when a refresh fails. The overview shows the worker heartbeat; pipelines are marked `STALE` when the last success exceeds the freshness SLA.

## Production considerations (not implemented)

Replace mock login with the bank's SSO/OIDC + MFA, move secrets to the approved secrets manager, add TLS termination, row-level security, retention jobs, real connectors through approved read-only interfaces, signed desktop installers distributed through the bank's software-distribution tooling.
