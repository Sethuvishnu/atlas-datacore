"""ORM models for ATLAS DataCore (Milestone 1 foundation schema).

Temporal modelling convention
-----------------------------
Facts that can change over time carry:
  valid_from / valid_to : when the fact was true in the market (valid_to NULL = open-ended)
  recorded_at           : when DataCore learned / recorded the fact
  source_id             : provenance
This lets us answer both "what was true on D?" and "what did we know on D?".
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.storage.database import Base


# ---------------------------------------------------------------- enums
class VerificationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"


class SecurityStatus(str, enum.Enum):
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    TEMPORARILY_INACTIVE = "TEMPORARILY_INACTIVE"
    DELISTED = "DELISTED"
    MERGED = "MERGED"
    UNKNOWN = "UNKNOWN"


class UniverseType(str, enum.Enum):
    ALL_ELIGIBLE = "ALL_ELIGIBLE"
    INDEX_MEMBERSHIP = "INDEX_MEMBERSHIP"


class CompletenessStatus(str, enum.Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class ConfidenceStatus(str, enum.Enum):
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    UNCERTAIN = "UNCERTAIN"


class PriceType(str, enum.Enum):
    RAW = "RAW"
    SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
    ACTION_ADJUSTED = "ACTION_ADJUSTED"


class ActionType(str, enum.Enum):
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    RIGHTS = "RIGHTS"
    DIVIDEND = "DIVIDEND"
    MERGER = "MERGER"
    DEMERGER = "DEMERGER"
    SYMBOL_CHANGE = "SYMBOL_CHANGE"
    ISIN_CHANGE = "ISIN_CHANGE"


class ImportStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class QualityStatus(str, enum.Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    # VARCHAR + CHECK constraint (not native PG enum): easier to evolve via migrations.
    return Enum(e, name=name, native_enum=False, create_constraint=True,
                length=32, values_callable=lambda x: [m.value for m in x])


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _recorded() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


# ---------------------------------------------------------------- sources & files
class DataSource(Base):
    __tablename__ = "data_source_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. EXCHANGE_ARCHIVE, MANUAL_UPLOAD
    permitted_usage: Mapped[str | None] = mapped_column(Text)
    update_frequency: Mapped[str | None] = mapped_column(String(64))
    historical_coverage: Mapped[str | None] = mapped_column(Text)  # documented, never assumed
    file_format: Mapped[str | None] = mapped_column(String(64))
    last_successful_import: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reliability_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="UNASSESSED")
    created_at: Mapped[datetime] = _created()


class RawDataFile(Base):
    __tablename__ = "raw_data_files"
    __table_args__ = (
        # Same bytes from the same source can only be registered once -> idempotent re-imports.
        UniqueConstraint("source_id", "checksum", name="uq_raw_data_files_source_checksum"),
        CheckConstraint("length(checksum) = 64", name="checksum_is_sha256_hex"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    file_date: Mapped[date | None] = mapped_column(Date)
    file_type: Mapped[str | None] = mapped_column(String(64))
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hex
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    import_status: Mapped[ImportStatus] = mapped_column(
        _enum(ImportStatus, "import_status"), nullable=False, server_default=ImportStatus.PENDING.value
    )


class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        CheckConstraint(
            "rows_processed >= 0 AND rows_inserted >= 0 AND rows_updated >= 0 AND rows_rejected >= 0",
            name="row_counts_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    file_id: Mapped[int | None] = mapped_column(ForeignKey("raw_data_files.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[ImportStatus] = mapped_column(
        _enum(ImportStatus, "import_status"), nullable=False, server_default=ImportStatus.RUNNING.value
    )
    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_rejected: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- security registry
class Security(Base):
    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("canonical_security_id", name="uq_securities_canonical_security_id"),
        # ISIN is the preferred stable identity, but may be unknown for some historical records.
        Index("uq_securities_isin_exchange_segment", "isin", "exchange", "segment",
              unique=True, postgresql_where="isin IS NOT NULL"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_security_id: Mapped[str] = mapped_column(String(64), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(12))
    company_name: Mapped[str | None] = mapped_column(String(256))
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    identifiers: Mapped[list[SecurityIdentifier]] = relationship(back_populates="security")


class SecurityIdentifier(Base):
    """Historical symbol / name / ISIN for a security (symbol changes preserve identity)."""

    __tablename__ = "security_identifiers"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        Index("ix_security_identifiers_symbol_valid", "symbol", "valid_from", "valid_to"),
        Index("ix_security_identifiers_security_id", "security_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(256))
    isin: Mapped[str | None] = mapped_column(String(12))
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = _recorded()
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus, "verification_status"), nullable=False,
        server_default=VerificationStatus.UNVERIFIED.value,
    )

    security: Mapped[Security] = relationship(back_populates="identifiers")


class SecurityStatusHistory(Base):
    __tablename__ = "security_status_history"
    __table_args__ = (
        CheckConstraint("end_date IS NULL OR end_date >= effective_date", name="date_range"),
        Index("ix_security_status_history_security_effective", "security_id", "effective_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    status: Mapped[SecurityStatus] = mapped_column(_enum(SecurityStatus, "security_status"), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = _recorded()
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- universe
class UniverseSnapshot(Base):
    __tablename__ = "universe_snapshots"
    # Snapshots are versioned (multiple rows per date allowed), never updated in place.
    __table_args__ = (
        Index("ix_universe_snapshots_lookup", "snapshot_date", "universe_type", "exchange", "segment"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    universe_type: Mapped[UniverseType] = mapped_column(_enum(UniverseType, "universe_type"), nullable=False)
    # e.g. "NIFTY50" for INDEX_MEMBERSHIP; "" for ALL_ELIGIBLE. Keeps universe definitions separate.
    universe_key: Mapped[str] = mapped_column(String(64), nullable=False, server_default="")
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    segment: Mapped[str] = mapped_column(String(16), nullable=False)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source_registry.id"))
    completeness_status: Mapped[CompletenessStatus] = mapped_column(
        _enum(CompletenessStatus, "completeness_status"), nullable=False,
        server_default=CompletenessStatus.UNKNOWN.value,
    )
    created_at: Mapped[datetime] = _created()


class UniverseMembership(Base):
    __tablename__ = "universe_membership"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="valid_range"),
        Index("ix_universe_membership_universe_security", "universe_id", "security_id"),
        Index("ix_universe_membership_valid", "valid_from", "valid_to"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    universe_id: Mapped[int] = mapped_column(ForeignKey("universe_snapshots.id"), nullable=False)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    recorded_at: Mapped[datetime] = _recorded()
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    confidence_status: Mapped[ConfidenceStatus] = mapped_column(
        _enum(ConfidenceStatus, "confidence_status"), nullable=False,
        server_default=ConfidenceStatus.UNCERTAIN.value,
    )


# ---------------------------------------------------------------- prices
class DailyPrice(Base):
    __tablename__ = "daily_prices"
    __table_args__ = (
        # One record per security/date within each price series (raw vs adjusted kept separate).
        UniqueConstraint("security_id", "trading_date", "price_type", name="uq_daily_prices_series"),
        CheckConstraint("volume IS NULL OR volume >= 0", name="volume_non_negative"),
        Index("ix_daily_prices_date", "trading_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    trading_date: Mapped[date] = mapped_column(Date, nullable=False)
    symbol_on_date: Mapped[str] = mapped_column(String(32), nullable=False)
    open: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    high: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    low: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    close: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    turnover: Mapped[Decimal | None] = mapped_column(Numeric(22, 2))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    import_id: Mapped[int | None] = mapped_column(ForeignKey("import_jobs.id"))
    price_type: Mapped[PriceType] = mapped_column(
        _enum(PriceType, "price_type"), nullable=False, server_default=PriceType.RAW.value
    )


# ---------------------------------------------------------------- corporate actions
class CorporateAction(Base):
    __tablename__ = "corporate_actions"
    __table_args__ = (
        Index("ix_corporate_actions_security_ex_date", "security_id", "ex_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    action_type: Mapped[ActionType] = mapped_column(_enum(ActionType, "action_type"), nullable=False)
    announcement_date: Mapped[date | None] = mapped_column(Date)  # NULL = unknown; point-in-time logic must respect this
    ex_date: Mapped[date | None] = mapped_column(Date)
    record_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    ratio: Mapped[str | None] = mapped_column(String(64))  # as published, e.g. "1:2"
    cash_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        _enum(VerificationStatus, "verification_status"), nullable=False,
        server_default=VerificationStatus.UNVERIFIED.value,
    )


class PriceAdjustment(Base):
    __tablename__ = "price_adjustments"
    __table_args__ = (
        CheckConstraint("adjustment_factor > 0", name="factor_positive"),
        Index("ix_price_adjustments_security_effective", "security_id", "effective_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), nullable=False)
    corporate_action_id: Mapped[int | None] = mapped_column(ForeignKey("corporate_actions.id"))
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    adjustment_factor: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    adjustment_type: Mapped[str] = mapped_column(String(32), nullable=False)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source_registry.id"), nullable=False)
    recorded_at: Mapped[datetime] = _recorded()


# ---------------------------------------------------------------- calendar & quality
class TradingCalendar(Base):
    __tablename__ = "trading_calendar"

    exchange: Mapped[str] = mapped_column(String(16), primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean, nullable=False)
    session_type: Mapped[str | None] = mapped_column(String(32))  # e.g. NORMAL, MUHURAT, SPECIAL
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source_registry.id"))


class DataQualityReport(Base):
    __tablename__ = "data_quality_reports"
    __table_args__ = (
        CheckConstraint(
            "total_records >= 0 AND missing_records >= 0 AND duplicate_records >= 0 AND invalid_records >= 0",
            name="counts_non_negative",
        ),
        Index("ix_data_quality_reports_dataset_date", "dataset_type", "report_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dataset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    quality_status: Mapped[QualityStatus] = mapped_column(_enum(QualityStatus, "quality_status"), nullable=False)
    total_records: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    missing_records: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    duplicate_records: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    invalid_records: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    warnings: Mapped[dict | list | None] = mapped_column(JSONB)  # structured: what was checked / what failed
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
