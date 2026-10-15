"""Driver choices for entry forms, without changing historical records."""

from datetime import date

from sqlalchemy import and_, or_

from haulage_app import db
from haulage_app.models import Driver, DriverEmploymentHistory, EmploymentStatus


def get_entry_drivers(selected_driver_id=None, on_date=None):
    """Return active drivers, optionally retaining an existing selection."""
    on_date = on_date or date.today()
    eligible = Driver.employment_history.any(and_(
        DriverEmploymentHistory.employment_status == EmploymentStatus.ACTIVE,
        DriverEmploymentHistory.start_date <= on_date,
        or_(
            DriverEmploymentHistory.end_date.is_(None),
            DriverEmploymentHistory.end_date >= on_date,
        ),
    ))
    try:
        selected_driver_id = int(selected_driver_id)
    except (TypeError, ValueError):
        selected_driver_id = None
    if selected_driver_id is not None:
        eligible = or_(eligible, Driver.id == selected_driver_id)
    return Driver.query.filter(eligible).order_by(
        Driver.first_name, Driver.last_name, Driver.id,
    ).all()


def with_selected_driver(drivers, selected_driver_id):
    """Keep an existing selection when correcting an old entry or a form error."""
    try:
        selected_driver_id = int(selected_driver_id)
    except (TypeError, ValueError):
        return drivers
    if any(driver.id == selected_driver_id for driver in drivers):
        return drivers
    selected_driver = db.session.get(Driver, selected_driver_id)
    if selected_driver is None:
        return drivers
    return sorted(
        [*drivers, selected_driver],
        key=lambda driver: (driver.first_name, driver.last_name, driver.id),
    )
