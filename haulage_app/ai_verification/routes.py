import os
import google.generativeai as genai
# from haulage_app.notification.models import Notification
# from haulage_app.ai_verification.models import VerificationFeedback
from datetime import datetime, timedelta
from haulage_app.models import Driver, Day, Fuel, Job, Payslip, Truck
import json
from pprint import pprint
from haulage_app import db
from haulage_app.functions import query_to_dict, date_to_db
import logging


class GeminiVerifier:
    def __init__(self):
        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
        self.model = genai.GenerativeModel('gemini-1.5-pro')
        # models = genai.list_models()
        # print("Available Gemini models:")
        # for model in models:
        #     print(f"- {model.name}")

    def process_llm_missing_data_response(self, llm_response, historical_context, Table):
        try:
            ai_response_entry = RawResponse(
                raw_response = llm_response,
                historical_context = historical_context
            )
            db.session.add(ai_response_entry)
            db.session.commit()
        except Exception as e:
            logging.exception(
                f"Error commiting to AiResponse: {e}, Response: {llm_response}, \
                Historical context: {historical_context}"
            )
            print(
               f"Error commiting to AiResponse: {e}, Response:, \
                Historical context: "
            )
            db.session.rollback()
            return False
        else:
            ai_response_entry_id = ai_response_entry.id
            print(f"Successfully added response: {ai_response_entry_id} to AiResponse")

            try:
                # Parse the JSON response
                missing_entries = json.loads(llm_response.strip())

                # Validate it's a list
                if not isinstance(missing_entries, list):
                    raise ValueError("Response is not a list format")

                new_entries = []
                # Process each missing_entry
                for entry in missing_entries:
                    # Create new database entry
                    new_entry = MissingEntry(
                        ai_response_id = ai_response_entry.id,
                        date = date_to_db(entry['anomaly_date']),
                        driver_id = entry['anomaly_identifier_id'],
                        table_name = TableName[Table.__name__.upper()]
                    )
                    # Check if missing entry exists
                    existing_record = Table.query.filter(
                        Table.driver_id == entry['anomaly_identifier_id'],
                        Table.date == date_to_db(entry['anomaly_date'])
                    ).first()
                    repeated_record = MissingAnomaly.query.filter(
                        MissingAnomaly.driver_id == entry['anomaly_identifier_id'],
                        MissingAnomaly.date == date_to_db(entry['anomaly_date'])
                    ).first()
                    if existing_record:
                        new_entry.suggestion_exists = True
                        ai_response_entry.all_suggestions_helpful = False
                        db.session.add(ai_response_entry)
                    if repeated_record:
                        new_entry.suggestion_repeated = True
                        ai_response_entry.all_suggestions_helpful = False
                        db.session.add(ai_response_entry)
                        
                    new_entries.append(new_entry)
                    print('new entry appended')
                    # Add to database
                db.session.add_all(new_entries)
                db.session.commit()
                    
            except json.JSONDecodeError:
                logging.error(f"Invalid JSON received from LLM: {llm_response}, Historical context: {historical_context}")
                print(f"Invalid JSON received from LLM:, Historical context: ")
                db.session.rollback()
                ai_response_entry.processing_successful = False
                db.session.commit()
                return False
            except KeyError as e:
                logging.error(f"Missing key in JSON response: {e}, Response: {llm_response}, Historical context: {historical_context}")
                print(f"Missing key in JSON response: {e}, Response:, Historical context: ")
                db.session.rollback()
                ai_response_entry.processing_successful = False
                db.session.commit()
                return False
            except ValueError as e:
                logging.error(f"Invalid data format: {e}, Response: {llm_response}, Historical context: {historical_context}")
                print(f"Invalid data format: {e}, Response:, Historical context: ")
                db.session.rollback()
                ai_response_entry.processing_successful = False
                db.session.commit()
                return False
            except Exception as e:
                logging.exception(f"An unexpected error occurred: {e}, Response: {llm_response}, Historical context: {historical_context}")
                print(f"An unexpected error occurred: {e}, Response:, Historical context: ")
                db.session.rollback()
                ai_response_entry.processing_successful = False
                db.session.commit()
                return False
            else:
                print("Successfully added raw ai response.")
                return True


    def llm_detect_missing_payslips(self):

        historical_context = {}
        query_to_dict(historical_context, Driver)
        query_to_dict(historical_context, Payslip)

        llm_response = self.model.generate_content(
            f"""
            Analyze this historical data for missing payslips across ALL drivers: {historical_context}

            Each driver gets paid every Friday.

            Check every driver's payslip history systematically. For each missing payslip, provide:
            [
                {{
                    "anomaly_date": "DD/MM/YYYY",
                    "day_of_week": "Monday",
                    "anomaly_identifier": "John Doe",
                    "anomaly_identifier_id: "1",
                }}
            ]
            
            Return only the raw array. No code blocks, no explanations, no additional formatting.
            """
        )

        pprint(llm_response.text)
        
        return llm_response.text, historical_context, Payslip


    def verify_missing_payslip(self):

        historical_context = {'payslips': {}}
        
        for payslip in Payslip.query.all():
            historical_context['payslips'][payslip_id] = {
                column.name: getattr(payslip, column.name) 
                for column in Payslip.__table__.columns
            }
            # historical_context[payslip.id]['driver_name'] = payslip.driver.full_name   
        # print(historical_context.__len__())

        # historical_context['all_day_entries'][day.id] = day_data
            
        llm_response = self.model.generate_content(
            f"""
            Analyze this historical data for patterns and anomalies: {historical_context}

            Check every driver's payslip history systematically. For each missing payslip across ALL drivers, provide:
            [
                {{
                    "anomaly_date": "DD/MM/YYYY",
                    "day_of_week": "Monday",
                    "anomaly_driver_name": "John Doe",
                    "anomaly_driver_id": integer
                }}
            ]
            
            Return only the raw array. No code blocks, no explanations, no additional formatting.
            """)

        print(llm_response.text)
        formatted_result = self.process_llm_response(llm_response.text, 1)
        # print(formatted_result)
        if formatted_result:
            return formatted_result
        else:
            return None


######################################################################################
    def verify_missing_fuel(self):

        historical_context = {'day_data': {}, 'fuel_invoices': {}}
        
        for fuel in Fuel.query.all():
            fuel_invoice = {
                column.name: getattr(fuel, column.name) 
                for column in Fuel.__table__.columns
            }
            historical_context['fuel_invoices'][fuel.id] = fuel_invoice
            historical_context['fuel_invoices'][fuel.id]['truck_registration'] = fuel.truck.registration
        
        # pprint(historical_context)

        for day in Day.query.filter(Day.date<=datetime(2024, 11, 1)).all():
            day_data = {
                column.name: getattr(day, column.name)
                for column in Day.__table__.columns
            }
            historical_context['day_data'][day.id] = day_data
            if day.truck:
                historical_context['day_data'][day.id]['truck_registration'] = day.truck.registration

        # pprint(historical_context)

        feedback = {26/11/2024: 
                        [{"anomaly_date": "16/09/2024", "day_of_week": "Monday",
                        "anomaly_truck_registration": "CE21 HFD", "anomaly_truck_id": 2, "helpful": True},
                        {"anomaly_date": "16/09/2024", "day_of_week": "Monday", 
                        "anomaly_truck_registration": "CA68 OXN", "anomaly_truck_id": 1, "helpful": True},
                        {"anomaly_date": "18/09/2024", "day_of_week": "Wednesday",
                        "anomaly_truck_registration": "CE24 FJV", "anomaly_truck_id": 3, "helpful": False},
                        {"anomaly_date": "19/09/2024", "day_of_week": "Thursday",
                        "anomaly_truck_registration": "CE21 HFD", "anomaly_truck_id": 2, "helpful": False},
                        {"anomaly_date": "19/09/2024", "day_of_week": "Thursday",
                        "anomaly_truck_registration": "CA68 OXN", "anomaly_truck_id": 1, "helpful": False},],
        27/11/2024 :
                        [{'anomaly_date': '16/09/2024', 'day_of_week': 'Monday',
                        'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': True}, 
                        {'anomaly_date': '16/09/2024', 'day_of_week': 'Monday', 
                        'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
                        {'anomaly_date': '18/09/2024', 'day_of_week': 'Wednesday', 
                        'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': True}, 
                        {'anomaly_date': '26/09/2024', 'day_of_week': 'Thursday', 
                        'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': False},],
        28/11/2024: 
            [
                {'anomaly_date': '24/09/2024', 'day_of_week': 'Tuesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
                {'anomaly_date': '26/09/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}, 
                {'anomaly_date': '27/09/2024', 'day_of_week': 'Friday', 'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': True}, 
                {'anomaly_date': '30/09/2024', 'day_of_week': 'Monday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}, 
                {'anomaly_date': '01/10/2024', 'day_of_week': 'Tuesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
                {'anomaly_date': '03/10/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
                {'anomaly_date': '03/10/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CE24 FJV', 'anomaly_truck_id': 3, 'helpful': False}, 
                {'anomaly_date': '08/10/2024', 'day_of_week': 'Tuesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
                {'anomaly_date': '09/10/2024', 'day_of_week': 'Wednesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}, 
                {'anomaly_date': '09/10/2024', 'day_of_week': 'Wednesday', 'anomaly_truck_registration': 'CE24 FJV', 'anomaly_truck_id': 3, 'helpful': False}, 
                {'anomaly_date': '10/10/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}
                ]}

#   ai pred.      ("[{'anomaly_date': '16/09/2024', 'anomaly_truck_registration': 'CE21 HFD', "
#  "'anomaly_truck_id': 2, 'explanation': 'Fuel marked as purchased in day entry "
#  "but no corresponding fuel entry found.'}, {'anomaly_date': '16/09/2024', "
#  "'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, "
#  "'explanation': 'Fuel marked as purchased in day entry but no corresponding "
#  "fuel entry found.'}, {'anomaly_date': '16/09/2024', "
#  "'anomaly_truck_registration': 'CE24 FJV', 'anomaly_truck_id': 3, "
#  "'explanation': 'Fuel marked as purchased in day entry but no corresponding "
#  "fuel entry found.'}]")
        
        # Use this feedback from the user: {feedback}
        # For each `day_entry` where `fuel` is True (meaning fuel was supposedly purchased) *and* the date is before 01/11/2024, verify that a corresponding `fuel_entry` exists with the same `truck_id` and `date`.

        # Conversely, for each `fuel_entry` *before* 01/11/2024, verify that a corresponding `day_entry` exists with `fuel` set to True and the same `truck_id` and `date`.
        cutoff_date = "1/11/2024"

        # If a `day_entry` with `fuel = True` has no matching `fuel_entry`, *or* if a `fuel_entry` has no corresponding `day_entry` with `fuel = True`, then it should be considered anomalous.
        llm_response = self.model.generate_content(
        f"""
        Analyze this historical data for missing fuel invoices. The data is comprised of day entries for each driver/truck, and fuel invoices for each truck: 
        
        {historical_context}

        Where fuel=True in a day entry, there should be a corresponding fuel invoice for the same truck and date.

        Check all of the history systematically and identify any discrepencies in the following format:

        [
            {{
                "anomaly_date": "DD/MM/YYYY",
                "anomaly_truck_registration": "CA68 OXN",
                "explanation": State whether a fuel entry is missing for a day entry with fuel=True, or a day entry with fuel=True is missing for a fuel entry.
            }}
        ]

        If no anomalous data is found, return an empty list: `[]`

        Return only the raw array. No code blocks, no explanations, no additional formatting.
        """
        )
        
            # f""""
            # Analyze this historical data for patterns and anomalies: {historical_context}
            
            # Format your response as a comma-separated list of ONLY the Day IDs that are anomalous.
            # Example format: 1,4,7
            
            # Do not include any other text or explanation
            # """)

        pprint(llm_response.text)
        return llm_response.text

        # formatted_result = self.process_llm_response(llm_response.text, 1)
        # print(formatted_result)
        # if formatted_result:
        #     return formatted_result
        # else:
        #     return None
        
    # def _get_historical_data(self, driver):
    #     # Get last 30 days of earnings for this driver
    #     history = DayEnd.query.filter_by(driver_id=driver.id).order_by(DayEnd.date.desc()).limit(30).all()
    #     return "\n".join([
    #         f"Date: {entry.date}, Earnings: £{entry.total_earned}"
    #         for entry in history
    #     ])
        
    # def _get_feedback_patterns(self):
    #     # Get verified patterns from feedback
    #     helpful_feedback = VerificationFeedback.query.filter_by(was_helpful=True).all()
    #     return "\n".join([
    #         f"Verified pattern: {feedback.verification_data}"
    #         for feedback in helpful_feedback
    #     ])

        for payslip in Payslip.query.all():
            payslip_data = {
                column.name: getattr(payslip, column.name)
                for column in Payslip.__table__.columns
            }


from flask import jsonify, request  # Import necessary modules

# ... other imports

# @ai_verification_bp.route('/verification-feedback/<int:formatted_anomaly_id>', methods=['POST'])
# def create_verification_feedback(formatted_anomaly_id):
#     """Creates VerificationFeedback for a given FormattedAnomaly."""
#     formatted_anomaly = FormattedAnomoly.query.get_or_404(formatted_anomaly_id)

#     is_helpful = request.form.get('is_helpful')

#     feedback = VerificationFeedback(
#         user_confirmed_alomaly=user_confirmed,
#         ai_response_id=ai_response_id,
#         formatted_anomaly_id=formatted_anomaly_id
#     )

#     db.session.add(feedback)
#     db.session.commit()

#     return jsonify({
#         'status': 'success',
#         'feedback_id': feedback.id
#     }), 201
