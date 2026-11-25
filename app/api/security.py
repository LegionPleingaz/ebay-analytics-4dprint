"""Protection du parcours OAuth.

Sans elle, n'importe qui pourrait lier son propre compte eBay et ecraser le
token stocke. /oauth/login exige HTTP Basic ; /oauth/callback exige un state
signe et recent, que seul /oauth/login emet.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import Settings, get_settings

STATE_TTL_SECONDS = 600
_basic = HTTPBasic()


def require_admin(
    credentials: HTTPBasicCredentials = Depends(_basic),
    settings: Settings = Depends(get_settings),
) -> None:
    """Identifiant libre, seul le mot de passe (ADMIN_PASSWORD) est verifie."""
    if not hmac.compare_digest(credentials.password.encode(), settings.admin_password.encode()):
        raise HTTPException(401, "Acces refuse", headers={"WWW-Authenticate": "Basic"})


def _sign(timestamp: str, settings: Settings) -> str:
    return hmac.new(settings.admin_password.encode(), timestamp.encode(), hashlib.sha256).hexdigest()


def create_state(settings: Settings, now: float | None = None) -> str:
    timestamp = str(int(time.time() if now is None else now))
    return f"{timestamp}.{_sign(timestamp, settings)}"


def is_valid_state(state: str, settings: Settings, now: float | None = None) -> bool:
    timestamp, _, signature = state.partition(".")
    if not timestamp.isdecimal():
        return False
    if not hmac.compare_digest(signature.encode(), _sign(timestamp, settings).encode()):
        return False
    age = (time.time() if now is None else now) - int(timestamp)
    return 0 <= age <= STATE_TTL_SECONDS
