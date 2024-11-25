import os
import google.generativeai as genai
# from haulage_app.notification.models import Notification
# from haulage_app.ai_verification.models import VerificationFeedback
from datetime import datetime, timedelta
from haulage_app.models import Driver, Day, Fuel, Job, Payslip, Truck
import json

class GeminiVerifier:
    def __init__(self):
        genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
        self.model = genai.GenerativeModel('gemini-1.5-pro')
        # print(self.list_models())

    def process_llm_response(self, verification_result, ai_response_id):
        try:
            # Parse the JSON response
            anomalies = json.loads(verification_result.text.strip())
            
            # Validate it's a list
            if not isinstance(anomalies, list):
                raise ValueError("Response is not a list format")
            
            test_results = []

            # Process each anomaly
            for anomaly in anomalies:
                # Create new database entry
                # new_anomaly = MissingAnomaly(
                #     anomaly_date = db.Column(db.Date),
                #     anomaly_driver_id = db.Column(db.Integer, db.ForeignKey('driver.id')),
                #     ai_response_id = db.Column(db.Integer, db.ForeignKey('ai_response.id')),
                # )
                # db.session.add(new_anomaly)
                
            # db.session.commit()
                test_result = {
                    'anomaly_date': anomaly['anomaly_date'],
                    'anomaly_driver_id': anomaly['anomaly_driver_id'],
                    'ai_response_id': ai_response_id,
                }
                test_results.append(test_result)
            
            print(test_results)
            return True
            
        except json.JSONDecodeError:
            # Handle invalid JSON
            return False
        except KeyError:
            # Handle missing expected fields
            return False
        except Exception as e:
            # Handle any other unexpected errors
            return False

    def verify_missing_payslip(self):
        historical_context = {}

        for payslip in Payslip.query.all():
            historical_context[payslip.id] = {
                column.name: getattr(payslip, column.name) 
                for column in Payslip.__table__.columns
            }
            historical_context[payslip.id]['driver_name'] = payslip.driver.full_name   
        # print(historical_context.__len__())

        
        # historical_context['all_day_entries'][day.id] = day_data
            
        verification_result = self.model.generate_content(
            f"""
            Analyze this historical data for patterns and anomalies: {historical_context}

            Check every driver's payslip history systematically. For each missing payslip across ALL drivers, provide:
            [
                {{
                    "asdf": "DD/MM/YYYY",
                    "asdf": "Monday",
                    "aase": "John Doe",
                    "gaser": integer
                }}
            ]
            
            Return only the raw array. No code blocks, no explanations, no additional formatting.
            """)
            # f""""
            # Analyze this historical data for patterns and anomalies: {historical_context}
            
            # Format your response as a comma-separated list of ONLY the Day IDs that are anomalous.
            # Example format: 1,4,7
            
            # Do not include any other text or explanation
            # """)
        self.process_llm_response(verification_result, 1)
        
        return verification_result
        
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

    def verify(self):
        historical_context = {'all_day_entries': {}}

        for day in Day.query.all():
            day_data = {
                'date': day.date,
                'driver_data': {
                    'driver': day.driver.full_name,
                    'status': day.status,
                    'total_earned': day.calculate_total_earned(),
                }
            }
            if day.status == 'working':
                day_data['truck_data'] = {
                    'truck': day.truck.registration,
                    'start_mileage': day.start_mileage,
                    'end_mileage': day.end_mileage,
                    'fuel_flag': day.fuel,
                }

        
        historical_context['all_day_entries'][day.id] = day_data
            
        #     verification_result = self.model.predict(prompt=data_to_verify)
        #     return verification_result
        # historical_context = self._get_historical_data(day_end.driver)
        # feedback_patterns = self._get_feedback_patterns()
        
        # Previous verification insights rated helpful:
        # {feedback_patterns}
        verification_result = self.model.generate_content(
            f"""
            Analyze this historical data for patterns and anomalies: {historical_context}
            
            Format your response as a comma-separated list of ONLY the Day IDs that are anomalous.
            Example format: 1,4,7
            
            Do not include any other text or explanation
            """)
        print(verification_result.text)
        
        return verification_result