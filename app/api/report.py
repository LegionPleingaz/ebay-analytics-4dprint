from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.security import require_admin
from app.config import Settings, get_settings
from app.db.base import get_db
from app.reports.monthly import NoData, generate

router = APIRouter()


@router.get("/report", response_class=PlainTextResponse, dependencies=[Depends(require_admin)])
def monthly_report(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
) -> PlainTextResponse:
    try:
        text = generate(db, settings)
    except NoData as exc:
        raise HTTPException(409, str(exc)) from exc
    return PlainTextResponse(text, headers={"Cache-Control": "no-store"})
