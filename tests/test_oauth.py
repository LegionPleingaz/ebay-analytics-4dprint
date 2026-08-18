import datetime as dt

import httpx
import pytest
import respx

from app.ebay.oauth import (
    ACCESS_TOKEN_REFRESH_MARGIN,
    OAuthError,
    exchange_code_for_tokens,
    get_valid_access_token,
    store_tokens,
)


TOKEN_URL = "https://api.sandbox.ebay.com/identity/v1/oauth2/token"


@respx.mock
def test_exchange_code_for_tokens_success(settings):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "AT-1",
                "expires_in": 7200,
                "refresh_token": "RT-1",
                "refresh_token_expires_in": 47304000,
                "token_type": "User Access Token",
            },
        )
    )
    payload = exchange_code_for_tokens("some-code", settings)
    assert payload["access_token"] == "AT-1"


@respx.mock
def test_exchange_code_for_tokens_raises_on_error(settings):
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(OAuthError):
        exchange_code_for_tokens("bad-code", settings)


def test_store_tokens_creates_row(db_session):
    payload = {
        "access_token": "AT-1",
        "expires_in": 7200,
        "refresh_token": "RT-1",
        "refresh_token_expires_in": 47304000,
        "scope": "scope-a scope-b",
    }
    token = store_tokens(db_session, payload)
    assert token.access_token == "AT-1"
    assert token.refresh_token == "RT-1"


def test_store_tokens_keeps_previous_refresh_token_if_missing(db_session):
    first = {
        "access_token": "AT-1",
        "expires_in": 7200,
        "refresh_token": "RT-1",
        "refresh_token_expires_in": 47304000,
        "scope": "scope-a",
    }
    store_tokens(db_session, first)

    # Reponse d'un refresh qui n'inclut pas de nouveau refresh_token
    second = {"access_token": "AT-2", "expires_in": 7200, "scope": "scope-a"}
    token = store_tokens(db_session, second, previous_refresh_token="RT-1")
    assert token.access_token == "AT-2"
    assert token.refresh_token == "RT-1"


def test_get_valid_access_token_raises_when_no_token(db_session, settings):
    with pytest.raises(OAuthError):
        get_valid_access_token(db_session, settings)


def test_get_valid_access_token_returns_existing_when_not_expiring(db_session, settings, now_utc):
    payload = {
        "access_token": "AT-fresh",
        "expires_in": 7200,
        "refresh_token": "RT-1",
        "refresh_token_expires_in": 47304000,
        "scope": "scope-a",
    }
    stored = store_tokens(db_session, payload)  # garder une reference : cf. note ci-dessous

    token = get_valid_access_token(db_session, settings)
    assert token == "AT-fresh"
    assert stored.access_token == "AT-fresh"


@respx.mock
def test_get_valid_access_token_refreshes_when_near_expiry(db_session, settings, now_utc):
    from app.db.models import OAuthToken

    token = OAuthToken(
        id=1,
        access_token="AT-old",
        refresh_token="RT-1",
        access_token_expires_at=now_utc + ACCESS_TOKEN_REFRESH_MARGIN - dt.timedelta(seconds=1),
        refresh_token_expires_at=now_utc + dt.timedelta(days=300),
        scopes="scope-a",
    )
    db_session.add(token)
    db_session.commit()

    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "AT-new",
                "expires_in": 7200,
                "refresh_token": "RT-2",
                "refresh_token_expires_in": 47304000,
                "scope": "scope-a",
            },
        )
    )

    result = get_valid_access_token(db_session, settings)
    assert result == "AT-new"


@respx.mock
def test_get_valid_access_token_raises_when_refresh_fails(db_session, settings, now_utc):
    from app.db.models import OAuthToken

    token = OAuthToken(
        id=1,
        access_token="AT-old",
        refresh_token="RT-1",
        access_token_expires_at=now_utc - dt.timedelta(seconds=1),
        refresh_token_expires_at=now_utc + dt.timedelta(days=300),
        scopes="scope-a",
    )
    db_session.add(token)
    db_session.commit()

    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(OAuthError):
        get_valid_access_token(db_session, settings)
