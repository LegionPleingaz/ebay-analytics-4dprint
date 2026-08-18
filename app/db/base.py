import datetime as dt
from collections.abc import Generator

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    # Toutes les colonnes dt.datetime sont mappees en TIMESTAMPTZ (timezone-aware) :
    # la logique metier (cooldown, expiration OAuth) compare systematiquement des
    # datetimes tz-aware, une colonne naive casserait ces comparaisons.
    type_annotation_map = {
        dt.datetime: DateTime(timezone=True),
    }


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False
        )
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
