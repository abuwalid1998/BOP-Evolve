"""Container healthcheck for the worker: healthy while its heartbeat is recent."""

import sys

from app.db import SessionLocal, utcnow
from app.models import ServiceHeartbeat

MAX_AGE_SECONDS = 90

with SessionLocal() as db:
    beat = db.get(ServiceHeartbeat, "pipeline-worker")
    healthy = beat is not None and (utcnow() - beat.last_beat_at).total_seconds() < MAX_AGE_SECONDS
sys.exit(0 if healthy else 1)
