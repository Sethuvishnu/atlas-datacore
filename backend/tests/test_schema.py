from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.storage import models as m
from app.storage.database import Base

EXPECTED_TABLES = {
    "securities", "security_identifiers", "security_status_history", "universe_snapshots",
    "universe_membership", "daily_prices", "corporate_actions", "price_adjustments",
    "trading_calendar", "raw_data_files", "import_jobs", "data_quality_reports",
    "data_source_registry",
}


def test_all_blueprint_tables_exist_in_migrated_db(engine):
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES == set(Base.metadata.tables)


def test_security_identity_survives_symbol_change(session, source, security):
    session.add_all([
        m.SecurityIdentifier(security_id=security.id, symbol="OLDSYM", valid_from=date(2020, 1, 1),
                             valid_to=date(2022, 12, 31), source_id=source.id),
        m.SecurityIdentifier(security_id=security.id, symbol="NEWSYM", valid_from=date(2023, 1, 1),
                             source_id=source.id),
    ])
    session.flush()
    rows = session.query(m.SecurityIdentifier).filter_by(security_id=security.id).all()
    assert {r.symbol for r in rows} == {"OLDSYM", "NEWSYM"}
    assert len({r.security_id for r in rows}) == 1


def test_temporal_range_rejects_valid_to_before_valid_from(session, source, security):
    session.add(m.SecurityIdentifier(security_id=security.id, symbol="X", valid_from=date(2023, 1, 1),
                                     valid_to=date(2022, 1, 1), source_id=source.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_status_history_rejects_end_before_effective(session, source, security):
    session.add(m.SecurityStatusHistory(security_id=security.id, status=m.SecurityStatus.SUSPENDED,
                                        effective_date=date(2023, 5, 1), end_date=date(2023, 4, 1),
                                        source_id=source.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_suspended_and_delisted_are_distinct_statuses(session, source, security):
    session.add_all([
        m.SecurityStatusHistory(security_id=security.id, status=m.SecurityStatus.SUSPENDED,
                                effective_date=date(2022, 1, 1), end_date=date(2022, 6, 30), source_id=source.id),
        m.SecurityStatusHistory(security_id=security.id, status=m.SecurityStatus.DELISTED,
                                effective_date=date(2023, 1, 1), source_id=source.id),
    ])
    session.flush()
    statuses = {r.status for r in session.query(m.SecurityStatusHistory).all()}
    assert statuses == {m.SecurityStatus.SUSPENDED, m.SecurityStatus.DELISTED}


def test_daily_price_unique_per_security_date_series(session, source, security):
    def price(**kw):
        return m.DailyPrice(security_id=security.id, trading_date=date(2022, 6, 15), symbol_on_date="T",
                            open=100, high=110, low=95, close=105, volume=10, source_id=source.id, **kw)
    session.add(price(price_type=m.PriceType.RAW))
    session.flush()
    # Same date, different series (adjusted) is allowed: raw and adjusted are kept separate.
    session.add(price(price_type=m.PriceType.SPLIT_ADJUSTED))
    session.flush()
    # Duplicate raw record is rejected.
    session.add(price(price_type=m.PriceType.RAW))
    with pytest.raises(IntegrityError):
        session.flush()


def test_negative_volume_rejected(session, source, security):
    session.add(m.DailyPrice(security_id=security.id, trading_date=date(2022, 6, 15), symbol_on_date="T",
                             volume=-1, source_id=source.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_same_file_checksum_cannot_be_registered_twice(session, source):
    def f(**kw):
        return m.RawDataFile(filename="a.csv", source_id=source.id, checksum="a" * 64,
                             storage_path="data/raw/a.csv", **kw)
    session.add(f())
    session.flush()
    session.add(f())
    with pytest.raises(IntegrityError):
        session.flush()


def test_checksum_must_be_sha256_length(session, source):
    session.add(m.RawDataFile(filename="a.csv", source_id=source.id, checksum="abc", storage_path="x"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_isin_unique_per_exchange_segment_but_nulls_allowed(session):
    mk = lambda cid, isin: m.Security(canonical_security_id=cid, isin=isin, exchange="NSE", segment="EQUITY")
    session.add_all([mk("N1", None), mk("N2", None)])  # unknown ISINs may repeat
    session.flush()
    session.add_all([mk("A1", "INE111A01011")])
    session.flush()
    session.add(mk("A2", "INE111A01011"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_adjustment_factor_must_be_positive(session, source, security):
    session.add(m.PriceAdjustment(security_id=security.id, effective_date=date(2022, 1, 1),
                                  adjustment_factor=0, adjustment_type="SPLIT", methodology="t",
                                  source_id=source.id))
    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_enum_value_rejected_by_db(session, source, security):
    from sqlalchemy import text
    with pytest.raises(IntegrityError):
        session.execute(text(
            "INSERT INTO security_status_history (security_id, status, effective_date, source_id) "
            "VALUES (:s, 'BANKRUPT', '2022-01-01', :src)"), {"s": security.id, "src": source.id})


def test_universe_types_are_separate_values(session, source):
    a = m.UniverseSnapshot(snapshot_date=date(2022, 6, 15), universe_type=m.UniverseType.ALL_ELIGIBLE,
                           exchange="NSE", segment="EQUITY", source_id=source.id)
    b = m.UniverseSnapshot(snapshot_date=date(2022, 6, 15), universe_type=m.UniverseType.INDEX_MEMBERSHIP,
                           universe_key="NIFTY50", exchange="NSE", segment="EQUITY", source_id=source.id)
    session.add_all([a, b])
    session.flush()
    session.refresh(a)
    assert a.completeness_status == m.CompletenessStatus.UNKNOWN  # never assume COMPLETE
