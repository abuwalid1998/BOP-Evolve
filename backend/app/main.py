import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, auth, cases, config, dashboard, insights, learning, ops, reports, rules
from app.config import get_settings
from app.db import SessionLocal, utcnow

settings = get_settings()
settings.assert_safe_for_environment()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(
    title="BOP Evolve API",
    version="0.1.0",
    description="Prototype API for BOP Evolve. Demo data is synthetic. Mock authentication is for local use only.",
)

# The Electron desktop shell serves the UI from the privileged ``app://bop-evolve`` origin.
DESKTOP_ORIGIN = "app://bop-evolve"
app.add_middleware(
    CORSMiddleware,
    allow_origins=[*settings.cors_origin_list, DESKTOP_ORIGIN],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "")
    request_id = (
        incoming if 8 <= len(incoming) <= 40 and incoming.replace("-", "").isalnum() else f"REQ-{uuid.uuid4().hex[:16]}"
    )
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    if settings.demo_mode:
        response.headers["X-Demo-Data"] = "synthetic"
    return response


for module in (auth, dashboard, cases, learning, insights, ops, reports, admin, config, rules):
    app.include_router(module.router)
app.include_router(config.public_router)


@app.get("/api/health", tags=["system"])
def health():
    db_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - health endpoint reports, never raises
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "demo_mode": settings.demo_mode,
        "auth_mode": settings.auth_mode,
        "time": utcnow().isoformat(),
        "version": app.version,
    }
