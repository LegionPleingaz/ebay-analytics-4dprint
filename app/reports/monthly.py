"""Rapport mensuel de detection sur les annonces pro. Lecture seule.

    python -m app.reports.monthly            # affiche le rapport
    python -m app.reports.monthly --email    # l'envoie aussi par e-mail
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerting.email_alerter import send_email
from app.business.cooldown import (
    COOLDOWN_DAYS,
    MAX_CHANGES_PER_WEEK,
    count_changes_in_last_7_days,
    get_last_change_at,
)
from app.business.detection import (
    Candidate,
    Finding,
    Kind,
    Metrics,
    Skip,
    Thresholds,
    evaluate,
    sort_key,
)
from app.business.scope import is_professional
from app.config import Settings, get_settings
from app.db.base import get_session_factory
from app.db.models import CollectionRun, Listing, ListingContentSnapshot, ListingSnapshot
from app.logging_config import configure_logging

STALE_DATA = dt.timedelta(days=9)

SECTIONS = {
    Kind.NO_SALE: (
        "Des vues mais aucune vente",
        "À examiner : prix, description ou frais de port.",
    ),
    Kind.LOW_CTR: (
        "Beaucoup d'impressions, peu de clics",
        "À examiner : titre ou photo principale.",
    ),
    Kind.LOW_VISIBILITY: (
        "Très peu d'impressions",
        "À examiner : mots-clés du titre et caractéristiques de l'objet.",
    ),
}


class NoData(RuntimeError):
    pass


@dataclass
class Report:
    run: CollectionRun
    generated_at: dt.datetime
    pro_count: int
    findings: list[Finding]
    skipped: dict[Skip, list[Candidate]]
    changes_last_7_days: int
    has_90d: bool


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite (tests) perd le fuseau ; Postgres le conserve."""
    if value is None or value.tzinfo:
        return value
    return value.replace(tzinfo=dt.timezone.utc)


def _observed_change_at(db: Session, listing_id: int) -> dt.datetime | None:
    """Date de la derniere collecte ou le titre ou le prix a change.

    Capte les modifications faites directement sur eBay, absentes de change_log.
    La date de constat est posterieure a la modification : cooldown prudent.
    """
    snapshots = db.execute(
        select(ListingContentSnapshot)
        .where(ListingContentSnapshot.listing_id == listing_id)
        .order_by(ListingContentSnapshot.collected_at)
    ).scalars().all()
    changed_at = None
    for previous, current in zip(snapshots, snapshots[1:]):
        if (previous.title, previous.price_value) != (current.title, current.price_value):
            changed_at = current.collected_at
    return _aware(changed_at)


def _metrics(snapshot: ListingSnapshot | None) -> Metrics | None:
    if snapshot is None:
        return None
    ctr = snapshot.click_through_rate
    return Metrics(
        impressions=snapshot.impressions_total,
        views=snapshot.views_total,
        click_through_rate=None if ctr is None else float(ctr),
        transactions=snapshot.transactions,
    )


def build_report(db: Session, thresholds: Thresholds, now: dt.datetime) -> Report:
    run = db.execute(
        select(CollectionRun)
        .where(CollectionRun.status.in_(("success", "partial")))
        .order_by(CollectionRun.started_at.desc())
        .limit(1)
    ).scalars().first()
    if run is None:
        raise NoData("Aucune collecte terminée : lancer d'abord le job hebdomadaire.")
    data_at = _aware(run.started_at)

    # Seules les annonces vues par ce run : une annonce terminee garde son
    # dernier statut "Active" en base.
    long_window = {
        s.listing_id: s
        for s in db.execute(
            select(ListingSnapshot).where(
                ListingSnapshot.run_id == run.id, ListingSnapshot.window == "90d"
            )
        ).scalars()
    }
    rows = db.execute(
        select(Listing, ListingContentSnapshot, ListingSnapshot)
        .join(ListingContentSnapshot, ListingContentSnapshot.listing_id == Listing.id)
        .outerjoin(
            ListingSnapshot,
            (ListingSnapshot.listing_id == Listing.id)
            & (ListingSnapshot.run_id == run.id)
            & (ListingSnapshot.window == "28d"),
        )
        .where(ListingContentSnapshot.run_id == run.id)
        .order_by(Listing.ebay_item_id)
    ).all()

    findings: list[Finding] = []
    skipped: dict[Skip, list[Candidate]] = defaultdict(list)
    pro_count = 0
    for listing, content, traffic in rows:
        if not is_professional(listing):
            continue
        pro_count += 1
        changes = [
            c
            for c in (
                _aware(get_last_change_at(db, listing.id)),
                _observed_change_at(db, listing.id),
            )
            if c
        ]
        candidate = Candidate(
            item_id=listing.ebay_item_id,
            title=content.title,
            start_time=_aware(listing.ebay_start_time),
            quantity=content.quantity,
            specifics_count=len(content.item_specifics or {}),
            metrics=_metrics(traffic),
            metrics_90d=_metrics(long_window.get(listing.id)),
            last_change_at=max(changes, default=None),
        )
        result = evaluate(candidate, thresholds, data_at=data_at, now=now)
        if isinstance(result, Skip):
            skipped[result].append(candidate)
        else:
            findings.extend(result)

    return Report(
        run=run,
        generated_at=now,
        pro_count=pro_count,
        findings=sorted(findings, key=sort_key),
        skipped=dict(skipped),
        changes_last_7_days=count_changes_in_last_7_days(db, now),
        has_90d=bool(long_window),
    )


def _finding_line(finding: Finding) -> str:
    c = finding.candidate
    m = finding.metrics
    ctr = "n/d" if m.click_through_rate is None else f"{m.click_through_rate:.0%}"
    line = (
        f"- {c.title}\n"
        f"  https://www.ebay.fr/itm/{c.item_id}\n"
        f"  sur {finding.window_days} jours : impressions {m.impressions} | vues {m.views} "
        f"| clics {ctr} | ventes {m.transactions}"
    )
    if finding.kind is Kind.LOW_VISIBILITY:
        line += f" | caractéristiques renseignées : {c.specifics_count}"
    if finding.mixes_versions:
        line += "\n  Attention : cette période inclut encore l'ancienne version de l'annonce."
    return line


def render(report: Report, thresholds: Thresholds, settings: Settings) -> str:
    local = lambda d: _aware(d).astimezone(settings.tzinfo).strftime("%d/%m/%Y %H:%M")  # noqa: E731
    run = report.run
    flagged = {f.candidate.item_id for f in report.findings}
    skipped_count = sum(len(v) for v in report.skipped.values())
    lines = [
        "RAPPORT MENSUEL - annonces pro 4DPrint",
        f"Collecte du {local(run.started_at)} (statut {run.status})",
    ]
    if run.traffic_report_generated_at_28d:
        lines.append(f"Trafic mis à jour par eBay le {local(run.traffic_report_generated_at_28d)}")
    if report.generated_at - _aware(run.started_at) > STALE_DATA:
        lines.append("ATTENTION : collecte de plus de 9 jours, vérifier la tâche planifiée.")
    if not report.has_90d:
        lines.append(
            "ATTENTION : pas de trafic 90 jours dans cette collecte, taux de clic et "
            "ventes évalués sur 28 jours."
        )
    lines += [
        "",
        f"{report.pro_count} annonces pro : {len(flagged)} à examiner, "
        f"{report.pro_count - len(flagged) - skipped_count} sans alerte, "
        f"{skipped_count} non évaluées.",
        f"Modifications journalisées sur 7 jours : {report.changes_last_7_days}"
        f"/{MAX_CHANGES_PER_WEEK}.",
        "Une annonce sans alerte n'est pas forcément performante : les seuils "
        "exigent un volume minimal.",
    ]

    if report.findings:
        top: list[str] = []
        for finding in report.findings:
            if finding.candidate.item_id not in top:
                top.append(finding.candidate.item_id)
        lines += ["", f"À traiter en premier : {', '.join(top[:MAX_CHANGES_PER_WEEK])}"]

    for kind, (title, advice) in SECTIONS.items():
        matching = [f for f in report.findings if f.kind is kind]
        if matching:
            lines += ["", f"== {title} ({len(matching)}) ==", advice]
            lines += [_finding_line(f) for f in matching]

    if len(report.findings) > len(flagged):
        lines += [
            "",
            "Une annonce a plusieurs alertes : ne modifier qu'un élément à la fois, "
            "et jamais le titre et le prix ensemble.",
        ]

    if report.skipped:
        lines += ["", "== Non évaluées =="]
        for reason, candidates in report.skipped.items():
            lines.append(f"{reason.value} : {len(candidates)}")
            lines += [f"- {c.item_id} {c.title}" for c in candidates]

    lines += [
        "",
        f"Seuils : impressions <= {thresholds.low_impressions_max} ; clics < "
        f"{thresholds.ctr_min:.0%} des {thresholds.ctr_min_impressions} impressions ; "
        f"0 vente avec plus de {thresholds.no_sale_views_over} vues. "
        f"Pause de {COOLDOWN_DAYS} jours après modification.",
        "Visibilité jugée sur 28 jours ; taux de clic et ventes sur 90 jours (28 si "
        "l'annonce a changé dans les 90 derniers jours).",
        "Les vues de l'annonce servent d'approximation des clics. Aucune annonce n'est modifiée.",
    ]
    return "\n".join(lines) + "\n"


def generate(db: Session, settings: Settings, now: dt.datetime | None = None) -> str:
    thresholds = settings.detection_thresholds
    report = build_report(db, thresholds, now or dt.datetime.now(dt.timezone.utc))
    return render(report, thresholds, settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", action="store_true", help="envoyer le rapport par e-mail")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        with get_session_factory()() as db:
            text = generate(db, settings)
        print(text)
        if args.email:
            if settings.alerting_backend != "email":
                raise RuntimeError("--email exige ALERTING_BACKEND=email")
            send_email(settings, "[ebay-analytics] Rapport mensuel", text)
            print("Rapport envoye par e-mail.")
    except Exception as exc:  # noqa: BLE001 - tache planifiee : signaler l'echec
        from app.alerting import get_alerter

        get_alerter().alert(
            subject="Rapport mensuel : echec",
            message=f"{type(exc).__name__}: {exc}"[:2000],
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
