import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.base import Base
from app.db import models  # noqa: F401


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            models.Listing.__table__,
            models.CollectionRun.__table__,
            models.ListingSnapshot.__table__,
            models.ChangeProposal.__table__,
            models.ChangeLog.__table__,
            models.OAuthToken.__table__,
            models.AlertState.__table__,
        ],
    )
    # expire_on_commit=False : coherent avec app.db.base.get_session_factory, et
    # evite que SQLite ne "relise" les datetimes sans leur tzinfo apres commit
    # (SQLite ignore silencieusement DateTime(timezone=True), cf. doc SQLAlchemy ;
    # Postgres en production stocke bien du TIMESTAMPTZ).
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        database_url="sqlite:///:memory:",
        ebay_env="sandbox",
        ebay_client_id="test-client-id",
        admin_password="test-admin-password",
        ebay_client_secret="test-client-secret",
        ebay_ru_name="test-ru-name",
        ebay_oauth_redirect_uri="https://example.test/oauth/callback",
    )


@pytest.fixture()
def now_utc() -> dt.datetime:
    return dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.timezone.utc)
