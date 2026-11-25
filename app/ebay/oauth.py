"""OAuth 2.0 user token flow (authorization code grant) + refresh persiste en base.

Endpoint documente : https://developer.ebay.com/api-docs/static/oauth-auth-code-grant-request.html
Refresh :            https://developer.ebay.com/api-docs/static/oauth-refresh-token-request.html

Le refresh token est persiste en base (table oauth_tokens, une seule ligne) car
une variable d'environnement Coolify ne se met pas a jour toute seule.
"""

from __future__ import annotations

import base64
import datetime as dt
import urllib.parse

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import OAuthToken
from app.logging_config import get_logger

logger = get_logger(__name__)

# Refresh proactivement 5 minutes avant expiration de l'access token.
ACCESS_TOKEN_REFRESH_MARGIN = dt.timedelta(minutes=5)

# Scopes demandes au consentement initial. Ajouter un scope plus tard exige un
# nouveau consentement utilisateur (cf. doc eBay) : demander tout ce qui est
# necessaire des maintenant.
SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.finances",
]


class OAuthError(RuntimeError):
    pass


def _basic_auth_header(settings: Settings) -> str:
    raw = f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    return base64.b64encode(raw).decode()


def build_consent_url(settings: Settings | None = None, *, state: str) -> str:
    settings = settings or get_settings()
    params = {
        "client_id": settings.ebay_client_id,
        "redirect_uri": settings.ebay_ru_name,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "state": state,
    }
    return f"{settings.ebay_auth_base}/oauth2/authorize?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    response = httpx.post(
        f"{settings.ebay_api_base}/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {_basic_auth_header(settings)}",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.ebay_ru_name,
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise OAuthError(f"Echange du code d'autorisation echoue: {response.status_code}")
    return response.json()


def _refresh_access_token(refresh_token: str, settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    response = httpx.post(
        f"{settings.ebay_api_base}/identity/v1/oauth2/token",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {_basic_auth_header(settings)}",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": " ".join(SCOPES),
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise OAuthError(f"Refresh du token echoue: {response.status_code} {response.text}")
    return response.json()


def store_tokens(db: Session, payload: dict, *, previous_refresh_token: str | None = None) -> OAuthToken:
    now = dt.datetime.now(dt.timezone.utc)
    access_expires_at = now + dt.timedelta(seconds=payload["expires_in"])

    # La reponse d'un refresh peut omettre refresh_token/refresh_token_expires_in
    # si eBay ne le renouvelle pas a chaque fois : on garde alors l'ancien.
    refresh_token = payload.get("refresh_token")
    if "refresh_token_expires_in" in payload:
        refresh_expires_at = now + dt.timedelta(seconds=payload["refresh_token_expires_in"])
    else:
        refresh_expires_at = None

    token = db.get(OAuthToken, 1)
    if token is None:
        token = OAuthToken(id=1)
        db.add(token)

    token.access_token = payload["access_token"]
    token.access_token_expires_at = access_expires_at
    if refresh_token:
        token.refresh_token = refresh_token
    elif previous_refresh_token and not getattr(token, "refresh_token", None):
        token.refresh_token = previous_refresh_token
    if refresh_expires_at is not None:
        token.refresh_token_expires_at = refresh_expires_at
    token.scopes = payload.get("scope", " ".join(SCOPES))

    db.commit()
    return token


def get_valid_access_token(db: Session, settings: Settings | None = None) -> str:
    """Retourne un access_token valide, en le rafraichissant si necessaire.

    Leve OAuthError si aucun token n'est en base (parcours OAuth jamais fait)
    ou si le refresh echoue.
    """
    settings = settings or get_settings()
    token = db.get(OAuthToken, 1)
    if token is None:
        raise OAuthError(
            "Aucun token OAuth en base. Effectuer le parcours de consentement "
            "(GET /oauth/login) avant de lancer une collecte."
        )

    now = dt.datetime.now(dt.timezone.utc)
    if token.access_token_expires_at - ACCESS_TOKEN_REFRESH_MARGIN > now:
        return token.access_token

    logger.info("oauth.refresh.start")
    try:
        payload = _refresh_access_token(token.refresh_token, settings)
    except OAuthError:
        logger.error("oauth.refresh.failed")
        raise

    token = store_tokens(db, payload, previous_refresh_token=token.refresh_token)
    logger.info("oauth.refresh.success", expires_at=token.access_token_expires_at.isoformat())
    return token.access_token
