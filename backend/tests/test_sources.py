from sqlalchemy import func, select

from app.sources.registry import SEED_SOURCES, UNVERIFIED, get_source, seed_sources
from app.storage.models import DataSource


def test_seed_creates_all_sources_and_is_idempotent(session):
    seed_sources(session)
    seed_sources(session)
    assert session.scalar(select(func.count()).select_from(DataSource)) == len(SEED_SOURCES)


def test_seed_never_claims_coverage_or_reliability(session):
    for src in seed_sources(session):
        assert src.historical_coverage == UNVERIFIED
        assert src.reliability_status == "UNASSESSED"
        assert src.last_successful_import is None


def test_seed_does_not_overwrite_operator_edits(session):
    seed_sources(session)
    src = get_source(session, "NSE_CM_UDIFF_BHAVCOPY")
    src.historical_coverage = "Checked 2026-11: 2023-01..2026-10 present"
    session.flush()
    seed_sources(session)
    assert get_source(session, "NSE_CM_UDIFF_BHAVCOPY").historical_coverage.startswith("Checked")


def test_get_source_unknown_raises(session):
    import pytest
    with pytest.raises(LookupError):
        get_source(session, "NOPE")
