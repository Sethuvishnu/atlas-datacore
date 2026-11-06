"""Data source registry (M2).

Every fact stored by DataCore points at a row here. Seed entries are deliberately conservative:
historical coverage is recorded as UNVERIFIED and reliability as UNASSESSED until someone has
actually checked a source. Nothing here asserts that an endpoint exists, is permitted, or covers
any period. URLs are only the public landing pages named in the project blueprint.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import DataSource

UNVERIFIED = "UNVERIFIED - not yet checked"
TERMS_NOTE = ("Subject to NSE terms of use. Use manual download / upload only; "
              "never bypass access restrictions. Permission not independently verified by DataCore.")


@dataclass(frozen=True)
class SourceSeed:
    name: str
    source_type: str
    url: str | None
    update_frequency: str | None
    file_format: str | None
    description: str


NSE_REPORTS = "https://www.nseindia.com/all-reports"

SEED_SOURCES: tuple[SourceSeed, ...] = (
    SourceSeed("NSE_CM_UDIFF_BHAVCOPY", "EXCHANGE_REPORT", NSE_REPORTS, "daily (trading days)", "ZIP/CSV",
               "NSE CM-UDiFF Common Bhavcopy (daily cash-market trades). Trade records only - not a membership list."),
    SourceSeed("NSE_LEGACY_BHAVCOPY", "EXCHANGE_REPORT", NSE_REPORTS, "daily (trading days)", "ZIP/CSV",
               "Older-format NSE equity bhavcopy archives. Format versions differ by period."),
    SourceSeed("NSE_CM_SECURITY_FILE", "EXCHANGE_REPORT", NSE_REPORTS, "daily", "CSV",
               "NSE CM security master / listed-securities file. A current file does NOT prove past membership."),
    SourceSeed("NSE_CM_PRICE_BAND", "EXCHANGE_REPORT", NSE_REPORTS, "daily", "CSV",
               "NSE CM price-band list."),
    SourceSeed("NSE_CORPORATE_ACTIONS", "EXCHANGE_REPORT", None, "as announced", "CSV",
               "NSE corporate-action records (splits, bonuses, dividends...). Locate via NSE website."),
    SourceSeed("NSE_SECURITY_WISE_ARCHIVE", "EXCHANGE_REPORT", None, "on demand", "CSV",
               "NSE security-wise historical price/volume archive. Locate via NSE website."),
    SourceSeed("MANUAL_UPLOAD", "MANUAL_UPLOAD", None, "ad hoc", "CSV/ZIP",
               "Files supplied by the operator. Provenance is whatever the operator records at upload."),
)


def seed_sources(session: Session) -> list[DataSource]:
    """Idempotently ensure the seed sources exist. Never overwrites operator-edited fields."""
    existing = {s.name: s for s in session.scalars(select(DataSource))}
    out: list[DataSource] = []
    for seed in SEED_SOURCES:
        src = existing.get(seed.name)
        if src is None:
            src = DataSource(
                name=seed.name, url=seed.url, source_type=seed.source_type,
                permitted_usage=TERMS_NOTE, update_frequency=seed.update_frequency,
                historical_coverage=UNVERIFIED, file_format=seed.file_format,
                reliability_status="UNASSESSED",
            )
            session.add(src)
        out.append(src)
    session.flush()
    return out


def get_source(session: Session, name: str) -> DataSource:
    src = session.scalar(select(DataSource).where(DataSource.name == name))
    if src is None:
        raise LookupError(f"Unknown data source {name!r}. Run seed_sources first.")
    return src
