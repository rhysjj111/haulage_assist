import datetime
import enum
from haulage_app import db
from haulage_app.base import Base
from haulage_app.functions import *
from haulage_app.models import str50, tstamp, date, intpk, driverfk, truckfk, dayfk
from typing_extensions import Annotated
from typing import List, Optional
from sqlalchemy.orm import validates, Mapped, mapped_column, relationship
from sqlalchemy import String, ForeignKey, Integer, DateTime, Date, func
from haulage_app.models import Driver, Truck, Day, Payslip, Job, Fuel
from sqlalchemy.dialects.postgresql import JSONB


text = Annotated[str, mapped_column(db.Text)]

class TableName(enum.Enum):
    DRIVER = 'driver'
    TRUCK = 'truck'
    DAY = 'day'
    JOB = 'job'
    FUEL = 'fuel'
    PAYSLIP = 'payslip'

class UserFeedback(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    anomaly_id: Mapped[int] = mapped_column(ForeignKey("anomaly.id", ondelete="CASCADE"))
    anomaly_invalid: Mapped[bool] = mapped_column(default=False)
    anomaly_rectified: Mapped[bool] = mapped_column(default=False)
    user_comment: Mapped[Optional[text]]

class Anomaly(db.Model):
    id: Mapped[intpk]
    timestamp: Mapped[tstamp]
    description: Mapped[Optional[text]]
    is_read: Mapped[bool] = mapped_column(default=False)
    is_recurring: Mapped[bool] = mapped_column(default=False)
    type: Mapped[str50] = mapped_column(nullable=False)
    week_number: Mapped[Optional[int]]
    year: Mapped[Optional[int]]

    __mapper_args__ = {
        'polymorphic_identity': 'anomaly',
        'polymorphic_on': type
    }

    user_feedbacks: Mapped[List["UserFeedback"]] = relationship(
        backref='anomaly', cascade='all, delete-orphan'
    )

class MissingEntryAnomaly(Anomaly):
    id: Mapped[int] = mapped_column(ForeignKey("anomaly.id", ondelete="CASCADE"), primary_key=True)
    date: Mapped[date]
    driver_id: Mapped[Optional[driverfk]]
    truck_id: Mapped[Optional[truckfk]]
    day_id: Mapped[Optional[dayfk]]
    table_name: Mapped[TableName]

    __mapper_args__ = {'polymorphic_identity': 'missing_entry'}

    driver: Mapped[Optional["Driver"]] = relationship(backref='anomalies')
    truck: Mapped[Optional["Truck"]] = relationship(backref='anomalies')

class IncorrectMileage(Anomaly):
    id: Mapped[int] = mapped_column(ForeignKey("anomaly.id", ondelete="CASCADE"), primary_key=True)
    previous_date: Mapped[date]
    next_date: Mapped[date]
    previous_end_mileage: Mapped[float]
    next_start_mileage: Mapped[float]
    truck_id: Mapped[Optional[truckfk]]
    previous_day_id: Mapped[Optional[int]] = mapped_column(ForeignKey("day.id"))
    next_day_id: Mapped[Optional[int]] = mapped_column(ForeignKey("day.id"))

    __mapper_args__ = {'polymorphic_identity': 'incorrect_mileage'}

    truck: Mapped[Optional["Truck"]] = relationship(backref='incorrect_mileages')
    previous_day: Mapped[Optional["Day"]] = relationship(foreign_keys=[previous_day_id], backref='incorrect_mileages')
    next_day: Mapped[Optional["Day"]] = relationship(foreign_keys=[next_day_id], backref='next_day_incorrect_mileages')


# class AiRawResponse(db.Model):
#     id: Mapped[intpk]
#     timestamp: Mapped[tstamp]
#     prompt: Mapped[text]
#     raw_response: Mapped[text]
#     historical_context_json = mapped_column(JSONB, nullable=True)

#     processed_responses: Mapped[List["AiProcessedResponse"]] = relationship(
#         backref='raw_response', cascade='all, delete-orphan'
#     )

#     def has_processed_responses(self):
#         """
#         Checks if any processed responses exist for this AiRawResponse.
#         Returns True or False
#         """
#         return len(self.processed_responses) > 0

#     def check_missing_suggestions_valid(self):
#         """
#         Checks all related MissingEntrySuggestion instances for False values in either
#         valid_suggestion or suggestion_repeated fields.  Also returns False
#         if there are no related MissingEntrySuggestion instances.

#         Returns:
#             bool: False if any related MissingEntrySuggestion instance has either
#                 valid_suggestion or suggestion_repeated set to False, or
#                 if there are no related MissingEntrySuggestion instances.
#                 True otherwise.
#         """

#         missing_entries = [entry for entry in self.processed_responses if isinstance(entry, MissingEntrySuggestion)]
        
#         if not missing_entries:
#             return False

#         for missing_entry in missing_entries:
#             if not missing_entry.valid_suggestion or not missing_entry.suggestion_repeated:
#                 return False
#         return True

#     def get_ai_response_missing_entry_suggestions(self):
#         """
#         Constructs a list of missing entry suggestions from AI responses.

#         Returns:
#             list: A list of dictionaries, each representing a missing entry suggestion, 
#                 in the format:
#                 [
#                     {
#                         "date": ...,
#                         "driver_id": ... or "truck_id": ...,  
#                         "data set": "..._data",
#                         "acceptable date?": ...,
#                     },
#                     ...
#                 ]
#         """
#         suggestions = []
#         if self.has_processed_responses():
#             for response in self.processed_responses:
#                 if response.type == "missing_entry":
#                     suggestion = {
#                         "date": display_date_iso(response.date),
#                         "data set": response.table_name.value + "_data",
#                         "acceptable date?": response.date_range_acceptable
#                     }
#                     if response.driver_id is not None:
#                         suggestion["driver_id"] = response.driver_id
#                     else:
#                         suggestion["truck_id"] = response.truck_id
#                     suggestions.append(suggestion)
#         return suggestions
    
#     def get_ai_response_missing_entry_context_and_suggestions(self):
#         """
#         Constructs a summary of AI responses, focusing on missing entry suggestions.

#         Returns:
#             dict: A dictionary containing a summary of AI responses in the format:
#                 {
#                     "ai_response_id": ...,
#                     "historical_context_string": ...,
#                     "missing_entry_suggestions": [
#                         {
#                             "date": ...,
#                             "driver_id": ... or "truck_id": ...,  
#                             "data set": "..._data",
#                             "helpful?": ... 
#                         },
#                         ...
#                     ]
#                 }
#         """
#         if not self.has_processed_responses():
#             return None  # Return None if no processed responses

#         summary = {
#             "ai_response_id": self.id,
#             "historical_context_string": self.historical_context_string,
#             "missing_entry_suggestions": [],
#         }

#         for response in self.processed_responses:
#             if response.type != "missing_entry":
#                 continue  # Skip if not a missing entry suggestion

#             suggestion = {
#                 "date": display_date_iso(response.date),
#                 "data set": response.table_name.value + "_data",
#                 "helpful?": bool(response.valid_suggestion and response.original_suggestion),
#             }

#             if response.driver_id is not None:
#                 suggestion["driver_id"] = response.driver_id
#             else:
#                 suggestion["truck_id"] = response.truck_id

#             summary["missing_entry_suggestions"].append(suggestion)

#         return summary



# class AiProcessedResponse(db.Model):
#     id: Mapped[intpk]
#     timestamp: Mapped[tstamp]
#     type: Mapped[str50] = mapped_column(nullable=False)
#     explanation: Mapped[Optional[text]]

#     ai_raw_response_id: Mapped[int] = mapped_column(ForeignKey('ai_raw_response.id', ondelete="CASCADE"))
#     ai_response_feedback: Mapped["AiResponseUserFeedback"] = relationship(
#         backref='ai_processed_response', 
#         uselist=False,
#         cascade='all, delete-orphan',
#         lazy='joined'
#     )
#     __mapper_args__ = {
#         'polymorphic_identity': 'ai_processed_response',
#         'polymorphic_on': type
#         }

#     @classmethod
#     def get_processed_response_count(cls):
#         return cls.query.count()

# class TableName(enum.Enum):
#     DRIVER = 'driver'
#     TRUCK = 'truck'
#     DAY = 'day'
#     JOB = 'job'
#     FUEL = 'fuel'
#     PAYSLIP = 'payslip'
#     table_name: Mapped[TableName]

# class MissingEntrySuggestion(AiProcessedResponse):
#     id: Mapped[int] = mapped_column(ForeignKey("ai_processed_response.id", ondelete="CASCADE"), primary_key=True)
#     date: Mapped[date]
#     driver_id: Mapped[Optional[driverfk]]
#     truck_id: Mapped[Optional[truckfk]]
#     table_name: Mapped[TableName]
#     # date_within_range: Mapped[Optional[bool]] = mapped_column(default=None) #True if the date range is acceptable
#     confirmed_missing_date: Mapped[Optional[bool]] = mapped_column(default=None) #True if the suggested missing record is missing
#     # original_suggestion: Mapped[Optional[bool]] = mapped_column(default=None) #True if the record has previously been suggested by ai.

#     __mapper_args__ = {'polymorphic_identity': 'missing_entry'}
#     driver: Mapped['Driver'] = relationship(uselist=False, lazy='joined')
#     truck: Mapped['Truck'] = relationship(uselist=False, lazy='joined')

# class AiResponseUserFeedback(db.Model):
#     # __table_args__ = (
#     # db.CheckConstraint(
#     #     'NOT (directly_helpful = TRUE AND indirectly_helpful = True)',
#     #     name='helpful_constraint'  # Give the constraint a descriptive name
#     # ),)
#     id: Mapped[intpk]
#     timestamp: Mapped[tstamp]
#     directly_helpful: Mapped[bool] # The suggestion was spot on.
#     indirectly_helpful: Mapped[bool] # The suggestion wasn't correct but led to a correction.
#     user_feedback: Mapped[Optional[str]]

#     processed_response_id: Mapped[int] = mapped_column(ForeignKey(
#         'ai_processed_response.id', ondelete="CASCADE"
#     ))

# class DayAnomalySuggestion(AiProcessedResponse):
#     id: Mapped[int] = mapped_column(ForeignKey("ai_processed_response.id", ondelete="CASCADE"), primary_key=True)
#     table_id: Mapped[int] = mapped_column(ForeignKey('day.id'))

#     day: Mapped['Day'] = relationship(backref='anomalies', lazy='joined')

#     __mapper_args__ = {'polymorphic_identity': 'day_anomaly'}


# # class JobAnomalySuggestion(AiProcessedResponse):
# #     id: Mapped[int] = mapped_column(ForeignKey("ai_processed_response.id", ondelete="CASCADE"), primary_key=True)
# #     job_id: Mapped[int] = mapped_column(ForeignKey('job.id'))

# #     job: Mapped['Job'] = relationship(backref='anomalies', lazy='joined')

# #     __mapper_args__ = {'polymorphic_identity': 'job_anomaly'}


# # class FuelAnomalySuggestion(AiProcessedResponse):
# #     id: Mapped[int] = mapped_column(ForeignKey("ai_processed_response.id", ondelete="CASCADE"), primary_key=True)
# #     fuel_id: Mapped[int] = mapped_column(ForeignKey('fuel.id'))

# #     fuel: Mapped['Fuel'] = relationship(backref='anomalies', lazy='joined')

# #     __mapper_args__ = {'polymorphic_identity': 'fuel_anomaly'}


# # class PayslipAnomalySuggestion(AiProcessedResponse):
# #     id: Mapped[int] = mapped_column(ForeignKey("ai_processed_response.id", ondelete="CASCADE"), primary_key=True)
# #     payslip_id: Mapped[int] = mapped_column(ForeignKey('payslip.id'))

# #     payslip: Mapped['Payslip'] = relationship(backref='anomalies', lazy='joined')

# #     __mapper_args__ = {'polymorphic_identity': 'payslip_anomaly'}

# class MissingEntrySuggestion(AiProcessedResponse):
#     id: Mapped[int] = mapped_column(ForeignKey("ai_processed_response.id", ondelete="CASCADE"), primary_key=True)
#     date: Mapped[date]
#     driver_id: Mapped[Optional[driverfk]]
#     truck_id: Mapped[Optional[truckfk]]
#     table_name: Mapped[TableName]
#     # date_within_range: Mapped[Optional[bool]] = mapped_column(default=None) #True if the date range is acceptable
#     confirmed_missing_date: Mapped[Optional[bool]] = mapped_column(default=None) #True if the suggested missing record is missing
#     # original_suggestion: Mapped[Optional[bool]] = mapped_column(default=None) #True if the record has previously been suggested by ai.

#     __mapper_args__ = {'polymorphic_identity': 'missing_entry'}
#     driver: Mapped['Driver'] = relationship(uselist=False, lazy='joined')
#     truck: Mapped['Truck'] = relationship(uselist=False, lazy='joined')




