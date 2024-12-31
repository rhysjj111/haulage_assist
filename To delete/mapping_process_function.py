import os
import google.generativeai as genai
from datetime import datetime, timedelta
from haulage_app.models import Driver, Day, Fuel, Job, Payslip, Truck, MissingAnomaly, TableName
import json
from pprint import pprint
from haulage_app import db
from haulage_app.functions import query_to_dict, date_to_db
import logging


class GeminiVerifier:
    def __init__(self):
        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
        self.model = genai.GenerativeModel('gemini-1.5-pro')

    def process_llm_missing_data_response(self, llm_response, historical_context, Table, ai_response_entry_id):

        try:
            anomalies = json.loads(llm_response.strip())

            if not isinstance(anomalies, list):
                raise ValueError("Response is not a list format")

            # Map table names to their respective ID columns and anomaly identifier keys
            table_id_mapping = {
                Payslip: {"id_column": Payslip.driver_id, "anomaly_key": "anomaly_driver_id"},
                Truck: {"id_column": Truck.id, "anomaly_key": "anomaly_truck_id"},
                Day: {"id_column": Day.driver_id, "anomaly_key": "anomaly_driver_id"},  # Or truck_id? Clarify based on your logic
                Job: {"id_column": Job.id, "anomaly_key": "job_id"}, # Placeholder. Decide on Job's anomaly identifier.
                # Add other tables as needed...
            }

            for anomaly in anomalies:
                new_anomaly = MissingAnomaly(
                    ai_response_id=ai_response_entry_id,
                    anomaly_date=date_to_db(anomaly['anomaly_date']),
                    table_name=TableName[Table.__name__.upper()] # Assign enum member here
                )

                mapping = table_id_mapping.get(Table)
                if not mapping:
                    raise ValueError(f"No mapping found for table: {Table.__name__}")

                id_column = mapping["id_column"]
                anomaly_key = mapping["anomaly_key"]

                setattr(new_anomaly, anomaly_key, anomaly['anomaly_identifier_id'])  # Set appropriate ID

                existing_record = Table.query.filter(
                    id_column == anomaly['anomaly_identifier_id'],
                    Table.date == date_to_db(anomaly['anomaly_date'])
                ).first()

                if existing_record:
                    new_anomaly.not_missing = True

                db.session.add(new_anomaly)

            db.session.commit()
            return True

        except (json.JSONDecodeError, KeyError, ValueError) as e:  # Combine exception handling
            logging.exception(f"Error processing LLM response: {e}, Response: {llm_response}, Context: {historical_context}")
            # Handle error (e.g., rollback, log, return False)
            db.session.rollback()
            return False  # Indicate failure

        except Exception as e:  # Catch other unexpected exceptions
            logging.exception(f"An unexpected error occurred: {e}, Response: {llm_response}, Context: {historical_context}")
            db.session.rollback()
            # Handle the exception
            return False # Indicate failure



    def llm_check_missing_payslips(self):

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
        
        return llm_response.text, historical_context, Payslip # Return Payslip table

