from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.security import create_state, is_valid_state, require_admin
from app.config import get_settings
from app.db.base import get_db
from app.ebay.oauth import OAuthError, build_consent_url, exchange_code_for_tokens, store_tokens

router = APIRouter(prefix="/oauth", tags=["oauth"])


@router.get("/login", dependencies=[Depends(require_admin)])
def login() -> RedirectResponse:
    """Point d'entree du parcours de consentement eBay (a ouvrir dans un navigateur)."""
    return RedirectResponse(build_consent_url(state=create_state(get_settings())))


@router.get("/callback")
def callback(
    code: str = Query(...), state: str = Query(""), db: Session = Depends(get_db)
) -> dict:
    """Callback OAuth - doit etre expose en HTTPS sur le domaine Coolify et
    declare comme RuName cote eBay Developer."""
    if not is_valid_state(state, get_settings()):
        raise HTTPException(403, "state invalide ou expire : recommencer depuis /oauth/login")
    try:
        payload = exchange_code_for_tokens(code)
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    token = store_tokens(db, payload)
    return {
        "status": "ok",
        "access_token_expires_at": token.access_token_expires_at.isoformat(),
        "refresh_token_expires_at": token.refresh_token_expires_at.isoformat(),
    }
