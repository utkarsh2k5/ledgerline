"""ORM models.

Every uploaded file becomes an immutable DatasetVersion (keyed by a hash of its
normalised content) and every row keeps a row_ref back to the file/cell it came
from. That's what lineage is built on. Newer versions win per (fund, month, source).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))  # admin | analyst | viewer
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Scheme(Base):
    __tablename__ = "schemes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="GBP")
    sponsor: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    funds: Mapped[list["Fund"]] = relationship(
        back_populates="scheme", order_by="Fund.sort_order"
    )


class Fund(Base):
    """A mandate held by the scheme (one manager, one asset class, one benchmark)."""

    __tablename__ = "funds"
    __table_args__ = (UniqueConstraint("scheme_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255))
    asset_class: Mapped[str] = mapped_column(String(80))
    manager: Mapped[str] = mapped_column(String(255))
    benchmark_name: Mapped[str] = mapped_column(String(255))
    target_weight: Mapped[float] = mapped_column(Float)  # strategic (policy) weight
    # Interest-rate sensitivity of the mandate in years (0 for growth assets).
    # LDI mandates are leveraged, so this can exceed the liability duration.
    effective_duration: Mapped[float] = mapped_column(Float, default=0.0)
    is_growth: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    scheme: Mapped[Scheme] = relationship(back_populates="funds")


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("scheme_id", "source", "content_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    # custodian | manager | benchmark | liabilities | curve
    source: Mapped[str] = mapped_column(String(30))
    adapter: Mapped[str] = mapped_column(String(60))
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    row_count: Mapped[int] = mapped_column(Integer)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    loaded_by: Mapped[str] = mapped_column(String(255))
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundMonth(Base):
    """One fund-month observation from one source.

    Custodian rows carry market values and flows (we compute the return);
    manager rows carry the manager's reported return.
    """

    __tablename__ = "fund_months"
    __table_args__ = (
        UniqueConstraint("dataset_version_id", "fund_id", "month"),
        Index("ix_fund_months_lookup", "fund_id", "source", "month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id"))
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"))
    source: Mapped[str] = mapped_column(String(30))
    month: Mapped[date] = mapped_column(Date)  # month-end date
    begin_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    reported_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    row_ref: Mapped[str] = mapped_column(String(255))


class BenchmarkMonth(Base):
    __tablename__ = "benchmark_months"
    __table_args__ = (UniqueConstraint("dataset_version_id", "fund_id", "month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id"))
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"))
    month: Mapped[date] = mapped_column(Date)
    ret: Mapped[float] = mapped_column(Float)
    row_ref: Mapped[str] = mapped_column(String(255))


class LiabilityCashflow(Base):
    __tablename__ = "liability_cashflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id"))
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    year: Mapped[int] = mapped_column(Integer)
    amount: Mapped[float] = mapped_column(Float)
    row_ref: Mapped[str] = mapped_column(String(255))


class CurvePoint(Base):
    __tablename__ = "curve_points"

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_version_id: Mapped[int] = mapped_column(ForeignKey("dataset_versions.id"))
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    as_of: Mapped[date] = mapped_column(Date)
    tenor_years: Mapped[float] = mapped_column(Float)
    par_yield: Mapped[float] = mapped_column(Float)
    row_ref: Mapped[str] = mapped_column(String(255))


class ReconRun(Base):
    __tablename__ = "recon_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run_by: Mapped[str] = mapped_column(String(255))
    tolerance_bps: Mapped[float] = mapped_column(Float)
    material_bps: Mapped[float] = mapped_column(Float)
    n_compared: Mapped[int] = mapped_column(Integer)
    n_matched: Mapped[int] = mapped_column(Integer)
    n_breaks: Mapped[int] = mapped_column(Integer)


class ReconBreak(Base):
    __tablename__ = "recon_breaks"
    __table_args__ = (Index("ix_breaks_open", "scheme_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    recon_run_id: Mapped[int] = mapped_column(ForeignKey("recon_runs.id"))
    fund_id: Mapped[int] = mapped_column(ForeignKey("funds.id"))
    month: Mapped[date] = mapped_column(Date)
    # value_mismatch | missing_custodian | missing_manager
    break_type: Mapped[str] = mapped_column(String(30))
    custodian_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    manager_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    diff_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    severity: Mapped[str] = mapped_column(String(20))  # minor | material
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | superseded
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)  # custodian|manager|override
    resolved_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    fund: Mapped[Fund] = relationship()


class ReportRun(Base):
    __tablename__ = "report_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("schemes.id"))
    spec_name: Mapped[str] = mapped_column(String(80))
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    commentary_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    commentary_issues: Mapped[list] = mapped_column(JSON, default=list)
    commentary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    commentary_provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)  # fmt -> relative path
    data_versions: Mapped[dict] = mapped_column(JSON, default=dict)
    gate_overridden: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LineageFact(Base):
    """Every number in a report, with how it was computed and where it came from."""

    __tablename__ = "lineage_facts"
    __table_args__ = (UniqueConstraint("report_run_id", "fact_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_run_id: Mapped[int] = mapped_column(ForeignKey("report_runs.id"), index=True)
    fact_id: Mapped[str] = mapped_column(String(160))
    label: Mapped[str] = mapped_column(String(255))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    formula: Mapped[str] = mapped_column(Text)
    inputs: Mapped[list] = mapped_column(JSON, default=list)
    sources: Mapped[list] = mapped_column(JSON, default=list)


class Job(Base):
    """Durable job queue backed by the database (no Redis needed).

    Workers claim jobs with ``SELECT ... FOR UPDATE SKIP LOCKED`` on Postgres,
    or an atomic conditional UPDATE on SQLite.
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status", "status", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(80))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
