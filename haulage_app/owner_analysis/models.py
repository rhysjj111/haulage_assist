"""Explicit owner overheads and review records, separate from payroll."""

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, validates

from haulage_app import db
from haulage_app.owner_analysis.dates import validate_week_start


MAX_STORED_INTEGER = 2147483647


def validate_nonnegative_integer(value, label):
    if type(value) is not int or not 0 <= value <= MAX_STORED_INTEGER:
        raise ValueError(f"{label} must be a whole number between 0 and {MAX_STORED_INTEGER}")
    return value


class OwnerOverheadSetting(db.Model):
    __tablename__ = "owner_overhead_setting"
    id: Mapped[int] = mapped_column(primary_key=True)
    effective_week_start: Mapped[date] = mapped_column(db.Date, nullable=False)
    truck_count: Mapped[int] = mapped_column(db.Integer, nullable=False)
    allowance_per_truck: Mapped[int] = mapped_column(db.Integer, nullable=False)
    __table_args__ = (
        db.UniqueConstraint("effective_week_start", name="uq_owner_overhead_effective_week"),
        db.CheckConstraint("truck_count >= 0", name="ck_owner_overhead_truck_count"),
        db.CheckConstraint("allowance_per_truck >= 0", name="ck_owner_overhead_allowance"),
    )

    @validates("effective_week_start")
    def validate_effective_week(self, key, value):
        return validate_week_start(value)

    @validates("truck_count", "allowance_per_truck")
    def validate_numbers(self, key, value):
        return validate_nonnegative_integer(value, key.replace("_", " "))

    @property
    def total(self):
        return self.truck_count * self.allowance_per_truck


class OwnerWeeklyOverhead(db.Model):
    __tablename__ = "owner_weekly_overhead"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(db.Date, nullable=False)
    truck_count: Mapped[int] = mapped_column(db.Integer, nullable=False)
    allowance_per_truck: Mapped[int] = mapped_column(db.Integer, nullable=False)
    source_setting_id: Mapped[int] = mapped_column(
        db.ForeignKey("owner_overhead_setting.id", ondelete="RESTRICT"), nullable=False
    )
    __table_args__ = (
        db.UniqueConstraint("week_start", name="uq_owner_weekly_overhead_week"),
        db.CheckConstraint("truck_count >= 0", name="ck_owner_weekly_truck_count"),
        db.CheckConstraint("allowance_per_truck >= 0", name="ck_owner_weekly_allowance"),
        db.Index("ix_owner_weekly_overhead_source_setting_id", "source_setting_id"),
    )

    @validates("week_start")
    def validate_week(self, key, value):
        return validate_week_start(value)

    @validates("truck_count", "allowance_per_truck")
    def validate_numbers(self, key, value):
        return validate_nonnegative_integer(value, key.replace("_", " "))

    @property
    def total(self):
        return self.truck_count * self.allowance_per_truck


def _review_note(value, *, required):
    if not isinstance(value, str):
        raise ValueError("Please enter a text note")
    value = value.strip()
    if required and not value:
        raise ValueError("Please explain what was checked")
    if len(value) > 4000:
        raise ValueError("Please keep notes within 4000 characters")
    return value


def _review_fingerprint(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Invalid review fingerprint; reload the report")
    return value


class OwnerIssueVerification(db.Model):
    """Append-only notes independent of deletable legacy anomalies/source rows."""
    __tablename__ = "owner_issue_verification"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(db.Date, nullable=False)
    scope_key: Mapped[str] = mapped_column(db.String(255), nullable=False)
    decision: Mapped[str] = mapped_column(db.String(32), nullable=False)
    note: Mapped[str] = mapped_column(db.Text, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(db.String(64), nullable=False)
    created_at = mapped_column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        db.CheckConstraint("decision IN ('verified', 'confirmed_zero', 'note')", name="ck_owner_issue_decision"),
        db.CheckConstraint("length(trim(note)) > 0", name="ck_owner_issue_note_required"),
        db.CheckConstraint("length(source_fingerprint) = 64", name="ck_owner_issue_fingerprint_length"),
        db.Index("ix_owner_issue_verification_week_scope", "week_start", "scope_key"),
    )

    @validates("week_start")
    def validate_week(self, key, value):
        return validate_week_start(value)

    @validates("scope_key")
    def validate_scope(self, key, value):
        if not isinstance(value, str) or not value.strip() or len(value) > 255:
            raise ValueError("Invalid verification scope")
        return value

    @validates("decision")
    def validate_decision(self, key, value):
        if value not in {"verified", "confirmed_zero", "note"}:
            raise ValueError("Invalid verification decision")
        return value

    @validates("note")
    def validate_note(self, key, value):
        return _review_note(value, required=True)

    @validates("source_fingerprint")
    def validate_fingerprint(self, key, value):
        return _review_fingerprint(value)


class OwnerWeekReview(db.Model):
    __tablename__ = "owner_week_review"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(db.Date, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(db.String(64), nullable=False)
    note: Mapped[str] = mapped_column(db.Text, nullable=False, default="", server_default="")
    created_at = mapped_column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    __table_args__ = (
        db.CheckConstraint("length(source_fingerprint) = 64", name="ck_owner_week_review_fingerprint_length"),
        db.Index("ix_owner_week_review_week_start", "week_start"),
    )

    @validates("week_start")
    def validate_week(self, key, value):
        return validate_week_start(value)

    @validates("note")
    def validate_note(self, key, value):
        return _review_note(value, required=False)

    @validates("source_fingerprint")
    def validate_fingerprint(self, key, value):
        return _review_fingerprint(value)

    @property
    def reviewed_at(self):
        return self.created_at
