from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import CollectionRun, OAuthToken

router = APIRouter()

# Au-dela de ce delai depuis le dernier run reussi, on considere la collecte
# hebdomadaire en retard (une panne silencieuse ne doit pas se decouvrir 3
# semaines plus tard).
STALE_RUN_THRESHOLD = dt.timedelta(days=9)


@router.get("/health/live")
def live() -> dict:
    """Le process repond. Utilise par Docker/Coolify : ne doit dependre ni d'OAuth
    ni du dernier run, sinon le proxy ne route jamais vers /oauth/login."""
    return {"status": "ok"}


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    checks: dict[str, dict] = {}
    overall_ok = True

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        # Endpoint public : pas de detail. Les requetes suivantes echoueraient aussi.
        response.status_code = 503
        return {"status": "degraded", "checks": checks}

    token = db.get(OAuthToken, 1)
    now = dt.datetime.now(dt.timezone.utc)
    if token is None:
        checks["oauth"] = {"ok": False, "error": "aucun token, parcours OAuth jamais effectue"}
        overall_ok = False
    else:
        refresh_ok = token.refresh_token_expires_at > now
        checks["oauth"] = {
            "ok": refresh_ok,
            "refresh_token_expires_at": token.refresh_token_expires_at.isoformat(),
        }
        if not refresh_ok:
            overall_ok = False

    last_run = db.execute(
        select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    if last_run is None:
        checks["last_weekly_run"] = {"ok": False, "error": "aucun run de collecte encore effectue"}
        overall_ok = False
    else:
        is_stale = (now - last_run.started_at) > STALE_RUN_THRESHOLD
        run_ok = last_run.status == "success" and not is_stale
        checks["last_weekly_run"] = {
            "ok": run_ok,
            "status": last_run.status,
            "started_at": last_run.started_at.isoformat(),
            "stale": is_stale,
        }
        if not run_ok:
            overall_ok = False

    response.status_code = 200 if overall_ok else 503
    return {"status": "ok" if overall_ok else "degraded", "checks": checks}
