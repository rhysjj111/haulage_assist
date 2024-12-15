import datetime
import enum
from haulage_app import db
from haulage_app.base import Base
from haulage_app.functions import *
from haulage_app.models import str50, tstamp, date, intpk, driverfk, truckfk
from typing_extensions import Annotated
from typing import List, Optional
from sqlalchemy.orm import validates, Mapped, mapped_column, relationship

text = Annotated[str, mapped_column(db.Text)]

class RawResponse(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    historical_context: Mapped[Optional[text]]
    raw_response: Mapped[text]
    processing_successful: Mapped[bool] = mapped_column(default=True) # This column will be ticked if formatting is successful, and user has verified each of the results as helpful.
    all_suggestions_helpful: Mapped[bool] = mapped_column(default=True)

    processed_responses: Mapped[List["ProcessedResponse"]] = relationship(
        backref='raw_response', cascade='all, delete-orphan'
    ) 
    # ai_response_feedback: Mapped[List["AiResponseUserFeedback"]] = relationship(
    #     backref='raw_response'
    # )

class ProcessedResponse(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    type: mapped[str50]
    explanation: Mapped[Optional[text]]

    raw_response_id: Mapped[int] = mapped_column(ForeignKey('raw_response.id'), ondelete="CASCADE")
    ai_response_feedback: Mapped["AiResponseUserFeedback"] = relationship(
        backref='processed_response', 
        uselist=False, 
        cascade='all, delete-orphan',
        lazy='joined'
    )
    __mapper_args__ = {'polymorphic_on': type}

class TableName(enum.Enum):
    DRIVER = 'driver'
    TRUCK = 'truck'
    DAY = 'day'
    JOB = 'job'
    FUEL = 'fuel'
    PAYSLIP = 'payslip'

class MissingEntry(ProcessedResponse):
    date: Mapped[date]
    driver_id: Mapped[Optional[driverfk]]
    truck_id: Mapped[Optional[truckfk]]
    table_name: Mapped[TableName]
    record_missing: Mapped[bool] = mapped_column(default=False) #True if the suggested missing record is missing
    suggestion_repeated: Mapped[bool] = mapped_column(default=False) #True if the record has previously been suggested by ai.

    driver: Mapped['Driver'] = relationship(uselist=False, lazy='joined')
    truck: Mapped['Truck'] = relationship(uselist=False, lazy='joined')

    __mapper_args__ = {'polymorphic_identity': 'missing_entry'}

class DayAnomaly(ProcessedResponse):
    day_id: Mapped[int] = mapped_column(ForeignKey('day.id'))

    day: Mapped['Day'] = relationship(backref='anomalies', lazy='joined')

    __mapper_args__ = {'polymorphic_identity': 'day_anomaly'}


class JobAnomaly(ProcessedResponse):
    job_id: Mapped[int] = mapped_column(ForeignKey('job.id'))

    job: Mapped['Job'] = relationship(backref='anomalies', lazy='joined')

    __mapper_args__ = {'polymorphic_identity': 'job_anomaly'}


class FuelAnomaly(ProcessedResponse):
    fuel_id: Mapped[int] = mapped_column(ForeignKey('fuel.id'))

    fuel: Mapped['Fuel'] = relationship(backref='anomalies', lazy='joined')

    __mapper_args__ = {'polymorphic_identity': 'fuel_anomaly'}


class PayslipAnomaly(ProcessedResponse):
    payslip_id: Mapped[int] = mapped_column(ForeignKey('payslip.id'))

    payslip: Mapped['Payslip'] = relationship(backref='anomalies', lazy='joined')

    __mapper_args__ = {'polymorphic_identity': 'payslip_anomaly'}


class AiResponseUserFeedback(db.Model):
    __table_args__ = (
    db.CheckConstraint(
        'NOT (directly_helpful = TRUE AND indirectly_helpful = True)',
        name='helpful_constraint'  # Give the constraint a descriptive name
    ),
    )
    processed_response_id: Mapped[int] = mapped_column(ForeignKey('processed_response.id'), primary_key=True)
    timestamp: Mapped[tstamp]
    directly_helpful: Mapped[bool] # The suggestion was spot on.
    indirectly_helpful: Mapped[bool] # The suggestion wasn't correct but led to a correction.



