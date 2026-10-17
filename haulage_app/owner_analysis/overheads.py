"""Explicit overhead changes; all reads preserve missing historical values."""

from dataclasses import dataclass
from datetime import date
import hashlib
import json

from haulage_app import db
from haulage_app.owner_analysis.dates import validate_week_start
from haulage_app.owner_analysis.models import (
    OwnerOverheadSetting, OwnerWeeklyOverhead, validate_nonnegative_integer,
)


@dataclass(frozen=True)
class EffectiveWeeklyOverhead:
    week_start: date
    truck_count: int
    allowance_per_truck: int
    source_setting_id: int

    @property
    def total(self):
        return self.truck_count * self.allowance_per_truck


def _fresh_query(model):
    query = model.query
    if not (db.session.new or db.session.dirty or db.session.deleted):
        query = query.populate_existing()
    return query


def _setting_for_week(week_start):
    return _fresh_query(OwnerOverheadSetting).filter(
        OwnerOverheadSetting.effective_week_start <= week_start
    ).order_by(OwnerOverheadSetting.effective_week_start.desc()).first()


def get_weekly_overhead(week_start):
    """Return a snapshot/effective values or None, without flushing or creating."""
    validate_week_start(week_start)
    with db.session.no_autoflush:
        snapshot = _fresh_query(OwnerWeeklyOverhead).filter_by(week_start=week_start).first()
        if snapshot is not None:
            return snapshot
        setting = _setting_for_week(week_start)
        if setting is None:
            return None
        return EffectiveWeeklyOverhead(week_start, setting.truck_count,
                                       setting.allowance_per_truck, setting.id)


def overhead_settings_fingerprint():
    """Protect forms that can change any effective week, including future ones."""
    with db.session.no_autoflush:
        settings = _fresh_query(OwnerOverheadSetting).order_by(
            OwnerOverheadSetting.effective_week_start, OwnerOverheadSetting.id
        ).all()
        values = [dict(id=row.id, effective_week_start=row.effective_week_start.isoformat(),
                       truck_count=row.truck_count, allowance_per_truck=row.allowance_per_truck)
                  for row in settings]
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def ensure_weekly_overhead(week_start):
    """Explicitly create only this week's snapshot. Caller owns commit/rollback."""
    validate_week_start(week_start)
    existing = OwnerWeeklyOverhead.query.filter_by(week_start=week_start).first()
    if existing is not None:
        return existing
    setting = _setting_for_week(week_start)
    if setting is None:
        return None
    snapshot = OwnerWeeklyOverhead(week_start=week_start, truck_count=setting.truck_count,
                                   allowance_per_truck=setting.allowance_per_truck,
                                   source_setting_id=setting.id)
    db.session.add(snapshot)
    db.session.flush()
    return snapshot


def set_overhead_settings(effective_week_start, truck_count, allowance_per_truck):
    """Change this and later saved weeks up to the next scheduled setting.

    Earlier weeks remain stable. An explicitly historical start is a deliberate
    correction; future precreated snapshots refresh too. No week is backfilled
    and no existing Expense/payroll entry is modified. Caller owns commit.
    """
    validate_week_start(effective_week_start)
    validate_nonnegative_integer(truck_count, "Truck count")
    validate_nonnegative_integer(allowance_per_truck, "Allowance per truck")
    setting = OwnerOverheadSetting.query.filter_by(effective_week_start=effective_week_start).first()
    if setting is None:
        setting = OwnerOverheadSetting(effective_week_start=effective_week_start)
        db.session.add(setting)
    setting.truck_count = truck_count
    setting.allowance_per_truck = allowance_per_truck
    db.session.flush()
    next_setting = OwnerOverheadSetting.query.filter(
        OwnerOverheadSetting.effective_week_start > effective_week_start
    ).order_by(OwnerOverheadSetting.effective_week_start).first()
    affected = OwnerWeeklyOverhead.query.filter(OwnerWeeklyOverhead.week_start >= effective_week_start)
    if next_setting is not None:
        affected = affected.filter(OwnerWeeklyOverhead.week_start < next_setting.effective_week_start)
    for snapshot in affected.all():
        snapshot.truck_count = truck_count
        snapshot.allowance_per_truck = allowance_per_truck
        snapshot.source_setting_id = setting.id
    db.session.flush()
    return setting
