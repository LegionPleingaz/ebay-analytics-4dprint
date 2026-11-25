import datetime as dt
import smtplib

import pytest
from pydantic import ValidationError

from app.alerting.email_alerter import EmailAlerter
from app.config import Settings
from app.db.models import AlertState, CollectionRun, OAuthToken
from app.monitoring.watchdog import REPEAT_AFTER, find_problems, notify

EMAIL = {
    "alerting_backend": "email",
    "smtp_host": "smtp.example.test",
    "smtp_user": "user",
    "smtp_password": "s3cret-smtp",
    "alert_email_from": "bot@example.test",
    "alert_email_to": "me@example.test",
}


def email_settings(settings: Settings, **extra) -> Settings:
    return Settings(**{**settings.model_dump(), **EMAIL, **extra})


class FakeSMTP:
    calls: list = []

    def __init__(self, host, port, **kwargs):
        self.calls.append(("connect", port))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self, context):
        self.calls.append(("starttls",))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, mail):
        self.calls.append(("send", mail["Subject"], mail["To"]))


class RecordingAlerter:
    def __init__(self, ok=True):
        self.ok, self.sent = ok, []

    def alert(self, *, subject, message, severity="error"):
        self.sent.append(subject)
        return self.ok


@pytest.fixture(autouse=True)
def reset_fake_smtp():
    FakeSMTP.calls = []


def test_email_uses_starttls_before_login(settings, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert EmailAlerter(email_settings(settings)).alert(subject="Sujet", message="m")
    assert [c[0] for c in FakeSMTP.calls] == ["connect", "starttls", "login", "send"]
    assert FakeSMTP.calls[-1][1:] == ("[ebay-analytics][error] Sujet", "me@example.test")


def test_email_port_465_uses_implicit_tls(settings, monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    assert EmailAlerter(email_settings(settings, smtp_port=465)).alert(subject="s", message="m")
    assert [c[0] for c in FakeSMTP.calls] == ["connect", "login", "send"]


def test_email_failure_returns_false_without_raising(settings, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("connexion refusee")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    assert EmailAlerter(email_settings(settings)).alert(subject="s", message="m") is False


def test_smtp_password_is_masked(settings):
    assert "s3cret-smtp" not in repr(email_settings(settings))


def test_incomplete_email_config_is_rejected(settings):
    with pytest.raises(ValidationError):
        email_settings(settings, smtp_host="")


def keys(db, now):
    return [p.key for p in find_problems(db, now)]


def add_token(db, now, expires_in_days):
    db.add(OAuthToken(
        id=1, access_token="a", refresh_token="r", scopes="s",
        access_token_expires_at=now + dt.timedelta(hours=1),
        refresh_token_expires_at=now + dt.timedelta(days=expires_in_days),
    ))
    db.commit()


def add_run(db, now, *, age, status="success"):
    db.add(CollectionRun(
        period_start=(now - age).date(), period_end=(now - age).date(),
        status=status, started_at=now - age,
    ))
    db.commit()


def test_empty_database_reports_missing_oauth_and_run(db_session, now_utc):
    assert keys(db_session, now_utc) == ["oauth_missing", "run_never"]


@pytest.mark.parametrize("age,status,expected", [
    (dt.timedelta(days=1), "success", []),
    (dt.timedelta(days=1), "partial", []),
    (dt.timedelta(days=10), "success", ["run_stale"]),
    (dt.timedelta(hours=3), "running", ["run_stuck"]),
    (dt.timedelta(minutes=5), "running", []),
    (dt.timedelta(days=1), "failed", ["run_failed"]),
])
def test_run_problems(db_session, now_utc, age, status, expected):
    add_token(db_session, now_utc, 300)
    add_run(db_session, now_utc, age=age, status=status)
    assert keys(db_session, now_utc) == expected


@pytest.mark.parametrize("days,expected", [(29, ["oauth_expiring"]), (-1, ["oauth_expired"])])
def test_oauth_expiry(db_session, now_utc, days, expected):
    add_token(db_session, now_utc, days)
    add_run(db_session, now_utc, age=dt.timedelta(days=1))
    assert keys(db_session, now_utc) == expected


def test_notify_throttles_then_repeats(db_session, now_utc):
    problems = find_problems(db_session, now_utc)
    alerter = RecordingAlerter()
    notify(db_session, problems, alerter, now_utc)
    notify(db_session, problems, alerter, now_utc + dt.timedelta(hours=6))
    assert len(alerter.sent) == 2
    notify(db_session, problems, alerter, now_utc + REPEAT_AFTER)
    assert len(alerter.sent) == 4


def test_notify_retries_when_delivery_fails(db_session, now_utc):
    problems = find_problems(db_session, now_utc)
    notify(db_session, problems, RecordingAlerter(ok=False), now_utc)
    assert db_session.query(AlertState).count() == 0


def test_notify_forgets_resolved_problems(db_session, now_utc):
    notify(db_session, find_problems(db_session, now_utc), RecordingAlerter(), now_utc)
    notify(db_session, [], RecordingAlerter(), now_utc)
    db_session.flush()
    assert db_session.query(AlertState).count() == 0
