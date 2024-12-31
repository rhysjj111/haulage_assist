# import os
# import json
# import google.generativeai as genai
# # from haulage_app.notification.models import Notification
# # from haulage_app.verification.models import VerificationFeedback
# import datetime
# from haulage_app.models import Driver, Day, Fuel, Job, Payslip, Truck
# from haulage_app.verification.models import AiRawResponse, MissingEntrySuggestion, TableName
# import json
# from sqlalchemy import desc, func
# from pprint import pprint
# from haulage_app import db
# from haulage_app.functions import query_to_dict, date_to_db, is_within_acceptable_date_range
# import logging

# class Gemini:
#     def __init__(self, model_name=None):
#         genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
#         if model_name is None:
#             model_name = 'gemini-1.5-pro-latest'
#             # model_name = 'gemini-2.0-flash-exp'
#         self.model = genai.GenerativeModel(model_name)


# class GeminiVerifier(Gemini):
#     def __init__(self, model_name=None):
#         super().__init__(model_name)

#     def process_llm_missing_data_response(self, llm_response, historical_context, Table):
#         try:
#             historical_context_json = json.dumps(historical_context)
#             ai_response_entry = AiRawResponse(
#                 raw_response = llm_response
#             )
#             db.session.add(ai_response_entry)
#             db.session.commit()
#         except Exception as e:
#             logging.exception(
#                 f"Error commiting to AiResponse: {e},"
#                 #      Response: {llm_response}, \
#                 # Historical context: {historical_context}"
                
#             )
#             db.session.rollback()
#             return False
#         else:
#             ai_response_entry_id = ai_response_entry.id
#             print(f"Successfully added response: {ai_response_entry_id} to AiResponse")

#             try:
#                 # Remove triple quotes
#                 llm_response = llm_response.replace('```', '')
#                 # Parse the JSON response
#                 missing_data_predictions = json.loads(llm_response.strip())

#                 # Validate it's a list
#                 if not isinstance(missing_data_predictions, list):
#                     raise ValueError("Response is not a list format")

#                 suggested_entries = []
#                 # Process each missing_entry
#                 for entry in missing_data_predictions:
#                     # Create new database entry
#                     suggested_entry = MissingEntrySuggestion(
#                         raw_response_id = ai_response_entry.id,
#                         date = date_to_db(entry['anomaly_date']),
#                         driver_id = entry['anomaly_identifier_id'],
#                         table_name = TableName.PAYSLIP,
#                         type = 'missing_entry',
#                         date_within_range = None,
#                         valid_suggestion = None,
#                         original_suggestion = None
#                     )
#                     anomaly_date = date_to_db(entry['anomaly_date'])
#                     start_date = datetime.date(2024,9,20)
#                     # Check if suggestion date is within acceptable range
#                     if not is_within_acceptable_date_range(anomaly_date, start_date):
#                         suggested_entry.date_within_range = False
#                     else:
#                         suggested_entry.date_within_range = True
#                         # Check if missing entry exists
#                         invalid_suggestion = Table.query.filter(
#                             Table.driver_id == entry['anomaly_identifier_id'],
#                             Table.date == anomaly_date
#                         ).first()
#                         if invalid_suggestion:
#                             suggested_entry.valid_suggestion = False
#                         else:
#                             suggested_entry.valid_suggestion = True
#                             # Check if missing entry is repeated
#                             repeated_record = MissingEntrySuggestion.query.filter(
#                                 MissingEntrySuggestion.driver_id == entry['anomaly_identifier_id'],
#                                 MissingEntrySuggestion.date == anomaly_date
#                             ).first()
#                             if repeated_record:
#                                 suggested_entry.original_suggestion = False
#                             else:
#                                 suggested_entry.original_suggestion = True
#                     suggested_entries.append(suggested_entry)
#                     print('new entry appended')
#                     # Add to database
#                 db.session.add_all(suggested_entries)
#                 db.session.commit()
                    
#             except json.JSONDecodeError:
#                 logging.exception(f"Invalid JSON received from LLM: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             except KeyError as e:
#                 logging.exception(f"Missing key in JSON response: {e}, Response: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             except ValueError as e:
#                 logging.exception(f"Invalid data format: {e}, Response: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             except Exception as e:
#                 logging.exception(f"An unexpected error occurred: {e}, Response: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             else:
#                 print("Successfully added raw ai response and processed responses.")
#                 return True

#     def process_llm_missing_data(self, llm_response, historical_context):
#         try:
#             historical_context_string = f"{historical_context}"
#             ai_response_entry = AiRawResponse(
#                 raw_response = llm_response,
#                 historical_context_string = historical_context_string
#             )
#             db.session.add(ai_response_entry)
#             db.session.commit()
#         except Exception as e:
#             logging.exception(
#                 f"Error commiting to AiResponse: {e},"
#                 #      Response: {llm_response}, \
#                 # Historical context: {historical_context}"
                
#             )
#             db.session.rollback()
#             return False
#         else:
#             ai_response_entry_id = ai_response_entry.id
#             print(f"Successfully added response: {ai_response_entry_id} to AiResponse")

#             try:
#                 # Remove triple quotes
#                 llm_response = llm_response.replace('```', '')
#                 llm_response = llm_response.replace('json','')
#                 llm_response = llm_response.replace("'",'"')
#                 # Parse the JSON response
#                 missing_data_predictions = json.loads(llm_response.strip())

#                 # Validate it's a list
#                 if not isinstance(missing_data_predictions, list):
#                     raise ValueError("Response is not a list format")

#                 suggested_entries = []

#                 model_map = {'fuel': Fuel, 'day': Day, 'payslip': Payslip}
#                 table_name_map = {'fuel': TableName.FUEL, 'day': TableName.DAY, 'payslip': TableName.PAYSLIP}

#                 # Process each missing_entry
#                 for entry in missing_data_predictions:
#                     # Create new database entry
#                     anomaly_date = date_to_db(entry['anomaly_date'])
#                     anomaly_id = entry['anomaly_identifier_id']
#                     start_date = datetime.date(2024,9,20)
#                     table_data = entry['from_dictionary']
#                     table_name = table_data.replace("_data", "")
#                     suggested_entry = MissingEntrySuggestion(
#                         raw_response_id = ai_response_entry.id,
#                         date = anomaly_date,
#                         table_name = table_name_map.get(table_name),
#                         type = 'missing_entry',
#                         date_within_range = None,
#                         valid_suggestion = None,
#                         original_suggestion = None
#                     )
#                     anomaly_identifier = entry['anomaly_identifier']
#                     if anomaly_identifier == "truck_id":
#                         suggested_entry.truck_id = anomaly_id
#                     else:
#                         suggested_entry.driver_id = anomaly_id
#                     # Check if suggestion date is within acceptable range
#                     if not is_within_acceptable_date_range(anomaly_date, start_date):
#                         suggested_entry.date_within_range = False
#                     else:
#                         suggested_entry.date_within_range = True
#                         # Check if missing entry exists
#                         table_model = model_map[table_name]
#                         if anomaly_identifier == "truck_id":
#                             invalid_suggestion = table_model.query.filter(
#                                 table_model.truck_id == anomaly_id,
#                                 table_model.date == anomaly_date
#                             ).first()
#                             if table_name == "fuel":
#                                 fuel_tag_true = Day.query.filter(
#                                     Day.truck_id == anomaly_id,
#                                     Day.date == anomaly_date,
#                                     Day.fuel == True
#                                 ).first()
#                                 if not fuel_tag_true:
#                                     invalid_suggestion = True
#                         else:
#                             if table_name == "fuel":
#                                 continue
#                             invalid_suggestion = table_model.query.filter(
#                                 table_model.driver_id == anomaly_id,
#                                 table_model.date == anomaly_date
#                             ).first()
#                             if table_name == "day":
#                                 if anomaly_date.weekday() == 5 or anomaly_date.weekday() == 6:
#                                     invalid_suggestion = True
#                         if invalid_suggestion:
#                             suggested_entry.valid_suggestion = False
#                         else:
#                             suggested_entry.valid_suggestion = True
#                             # Check if missing entry is repeated
#                             repeated_record = MissingEntrySuggestion.query.filter(
#                                 MissingEntrySuggestion.driver_id == anomaly_id,
#                                 MissingEntrySuggestion.date == anomaly_date
#                             ).first()
#                             if repeated_record:
#                                 suggested_entry.original_suggestion = False
#                             else:
#                                 suggested_entry.original_suggestion = True
#                     suggested_entries.append(suggested_entry)
#                     print('new entry appended')
#                     # Add to database
#                 db.session.add_all(suggested_entries)
#                 db.session.commit()
                    
#             except json.JSONDecodeError:
#                 logging.exception(f"Invalid JSON received from LLM: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             except KeyError as e:
#                 logging.exception(f"Missing key in JSON response: {e}, Response: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             except ValueError as e:
#                 logging.exception(f"Invalid data format: {e}, Response: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             except Exception as e:
#                 logging.exception(f"An unexpected error occurred: {e}, Response: \
#                     {llm_response}, Historical context: ")
#                 db.session.rollback()
#                 ai_response_entry.processing_successful = False
#                 db.session.commit()
#                 return False
#             else:
#                 print("Successfully added raw ai response and processed responses.")
#                 return True

#     def llm_detect_missing_payslips(self):

#         historical_context = {}
#         # query_to_dict(historical_context, Driver, relevant_attributes=['id', 'first_name', 'last_name'])
#         query_to_dict(historical_context, Payslip, relevant_attributes=['id', 'date', 'driver_id'])
#         query_to_dict(historical_context, Day, relevant_attributes=['id', 'date', 'driver_id', 'truck_id', 'fuel'])
#         query_to_dict(historical_context, Fuel, relevant_attributes=['id', 'date', 'truck_id'])
#         # query_to_dict(historical_context, Truck, relevant_attributes=['id', 'registration'])
    
#         # print(historical_context)
#         raw_responses = AiRawResponse.query.all()
#         previous_answers = []
#         for response in raw_responses:
#             previous_answers.append(response.get_ai_response_missing_entry_suggestions())

#         top_raw_responses = (
#             AiRawResponse.query
#             .join(AiRawResponse.processed_responses)  # Join with the related table
#             .filter(MissingEntrySuggestion.original_suggestion == True)  # Filter for True values
#             .group_by(AiRawResponse.id)  # Group by AiRawResponse ID
#             .order_by(desc(func.count(MissingEntrySuggestion.id)))  # Order by count in descending order
#             .limit(2)
#             .all()
#         )
#         top_previous_answers = []
#         for response in top_raw_responses:
#             top_previous_answers.append(response.get_ai_response_missing_entry_context_and_suggestions())
        

#         # print('PREVIOUS ANSWERS::::::::::', previous_answers)

#             # Read the below instructions. Do not carry them out. Instead, give me a summary of what you think I am asking.
#             # Is there anything confusing or unclear about the instructions?
#             # Act as an llm prompt engineer.
#             # Take a look at the below  instructions. Do not carry them out. Instead, give me a summary of what you think I am asking.
#             # Which bits are helpful, and which are confusing.
#             # Do the previous context and answers make sense?
#             # How would you suggest changing the strategy of using an llm to highlight missing entries for the user?
#         llm_response = self.model.generate_content(
#             f"""

#             Use the below historical context to carry out the tasks in the format requested.
#             You are looking for entries that you think are missing. The aim is to find missing entries, not to edit existing ones.
#             The historical context is data from a haulage company with three drivers and three trucks.
#             A week is defined as Monday to Sunday.
#             The working week is defined as Monday to Friday.

#             The data provided will have the following structure:
#             - It contains three seperate datasets: 'payslip_data', 'day_data', and 'fuel_data'.
#             - The date represents the date of the entry.
#             - driver_id is the unique identifier for each driver.
#             - truck_id is the unique identifier for each truck.
#             - If truck_id is None in a day_data entry, this indicates a holiday or absence and not important for any of the tasks.

#             1. Context:

#             1a. Good examples of previous answers with context:
#             {top_previous_answers}

#             1b. Current historical context:
#             {historical_context}

#             1c. Full list of previous suggestions:
#             {previous_answers}

#             2. Answer format:
#             2a. Please provide your answer as a list of dictionaries in the following format:
#             [
#                 {{
#                     "anomaly_date": "YYYY-MM-DD",
#                     "anomaly_identifier": "truck_id" or "driver_id" (must always be truck or driver id),
#                     "anomaly_identifier_id: "1",
#                     "from_dictionary": "..._data"
#                 }}
#             ]

#             2b. Return only the raw array. No code blocks, no explanations, no additional formatting.

#             2c. There may be no missing data, if no missing data is found, return 'None'.

#             3. Tasks
#             3a. Check for missing day_data.
#             Information to consider:
#             - Based on the provided historical data; identify any potential missing \
#                 entries in the `day_data` dataset.
#             - There should be a `day_data` entry for each driver for each workday (Monday to Friday).
#             - If there are fewer than 5 entries for a driver in a given working week (Monday to Friday), create a separate dictionary \
#                 in the output array for each missing entry; the anomoly_date representing each missing day date. \
#             - For example, if there are 3 entries in one week, Monday, Wednesday, Friday, create 2 separate dictionaries, each \
#                 representing one missing entry. The dates will be for the missing Tuesday and Thursday.
#             - For task 3a, focus only on the driver and date in `day_data`; the `truck_id` will be used in a later task.

#             3b. Check for missing fuel_data.
#             Information to consider:
#             - Analyze the provided `day_data` and `fuel_data`, and any relevant previous data, to identify any potential missing entries in the `fuel_data` dataset.
#             - The `fuel_data` represents fuel invoices received from the fuel supplier.
#             - In `day_data`, the `fuel_flag` boolean represents whether a driver has marked fuel as purchased for that day.
#             - In any given week (Mon to Fri), and any given truck, there should be an equal amount of fuel_data entries to day_data entries with fuel_flag = True.
#             - If there are less fuel_data entries than fuel_flag = True, for any given week and truck, fuel_data should be conscidered missing, \
#                 and can be located by finding the the day_data with fuel_flag=True with no corresponding fuel_data entry.
#             - Do nothing if there are multiple fuel data entries for a given truck and date, this is perfectly fine.
#             - The important thing is to note the missing fuel_data. There can be a fuel_data entry without the corresponding fuel flag, \
#                 but not the converse.
#             - Take these steps to complete the task:
#             3bi. For each truck and week, find the number of fuel_data entries.
#             3bii. For each truck and week, find the number of day_data entries with fuel_flag = True.
#             3biii. For each truck and week, find any weeks with less fuel_data entries than fuel_flag = True.
#             3biiii. Within these weeks, look for day_data with fuel_flag = True that do not have a corresponding fuel_data entry.
#             3biiiii. Create a dictionary for each missing fuel_data entry, with the anomoly_date representing the date of the missing fuel_data entry.


#             3c. Check for missing payslip_data.
#             Information to consider:
#             - Based on the provided historical data, identify any potential missing entries in the `payslip_data` dataset.
#             - The `payslip_data` represents payslips benerated by the payroll department.
#             - There should be one payslip_data entry for each driver for each working week (Monday to Friday). \
#             """
#             ,
#         generation_config=genai.types.GenerationConfig(
#             temperature=0,)
#         )

#         # print('LLM RESPONSE::::::::::', llm_response.text)
        
#         return llm_response.text, historical_context
#         # llm_response = self.model.generate_content(
#         #     f"""

#         #     Use the below information to carry out the following tasks

#         #     INFORMATION:
#         #     The driver_id is a unique identifier for each driver.
#         #     The truck_id is a unique identifier for each truck.
#         #     The date is the date of the entry.
#         #     The status is the driver's status of the day; 'working', 'absent' or 'holiday'.
#         #     The fuel in 'day_data' is an indicator marked by the driver if fuel was purchased.
#         #     The fuel_data are actual fuel invoices received.
#         #     There should be a minimum of 5 day entries for each driver per week.
#         #     The drivers get paid weekly.

#         #     Current historical context:
#         #     {historical_context}

#         #     TASKS:
#         #     1. Systematically check through fuel_data, payslip_data and day_data. 
#         #     Check between 20/09/2024 and 20/12/2024.
#         #     Make a note of any potential missing data.
#         #     2. Format the suggested missing entries as below:
#         #     Return only the raw array. No code blocks, no explanations, no additional formatting.
#         #     For suggested missing entries, provide:
#         #     [
#         #         {{
#         #             "anomaly_date": "DD/MM/YYYY",
#         #             "anomaly_identifier": "truck_id" or "driver_id",
#         #             "anomaly_identifier_id: "1",
#         #             "from_dictionary": "..._data",
#         #         }}
#         #     ]
#         #     3. If no missing data is found, return an empty list: `[]`
#         #     """
#         #     ,
#         # generation_config=genai.types.GenerationConfig(
#         #     temperature=0.2,)
#         # )

#         # llm_response = self.model.generate_content(
#         #     f"""
#         #     Previous context and answers:
#         #     {previous_answers}

#         #     Current historical context:
#         #     {historical_context}

#         #     Analyze this historical data for missing entries, using the previous context and answers for guidance.
#         #     Each driver gets paid at the end of the working week, typically Friday.
#         #     Apply check between 20/09/2024 and 20/12/2024.
            
#         #     Return only a maximum of 3, high quality results. If no missing data is found, return an empty list: `[]`
#         #     Return only the raw array. No code blocks, no explanations, no additional formatting.

#         #     ONLY, if a date and driver is not found, provide:
#         #     [
#         #         {{
#         #             "anomaly_date": "DD/MM/YYYY",
#         #             "day_of_week": "Monday",
#         #             "anomaly_identifier": "John Doe",
#         #             "anomaly_identifier_id: "1",
#         #         }}
#         #     ]
#         #     OTHERWISE, provide an empty list: []
#         #     """
#         #     ,
#         # generation_config=genai.types.GenerationConfig(
#         #     temperature=0,)
#         # )
        
#         # llm_response = self.model.generate_content(
#         #     f"""
#         #     Previous context and answers:
#         #     {previous_answers}

#         #     Current historical context:
#         #     {historical_context}

#         #     Is there a payslip to account for each driver for every week between 20/09/2024 and 20/12/2024?

#         #     Return only the word True or False.

#         #     """
#         #     ,
#         # generation_config=genai.types.GenerationConfig(
#         #     temperature=0,)
#         # )

#         # return llm_response.text, historical_context, Payslip
#         # return True


#     def verify_missing_payslip(self):

#         historical_context = {'payslips': {}}
        
#         for payslip in Payslip.query.all():
#             historical_context['payslips'][payslip_id] = {
#                 column.name: getattr(payslip, column.name) 
#                 for column in Payslip.__table__.columns
#             }
#             # historical_context[payslip.id]['driver_name'] = payslip.driver.full_name   
#         # print(historical_context.__len__())

#         # historical_context['all_day_entries'][day.id] = day_data
            
#         llm_response = self.model.generate_content(
#             f"""
#             Analyze this historical data for patterns and anomalies: {historical_context}

#             Check every driver's payslip history systematically. For each missing payslip across ALL drivers, provide:
#             [
#                 {{
#                     "anomaly_date": "DD/MM/YYYY",
#                     "day_of_week": "Monday",
#                     "anomaly_driver_name": "John Doe",
#                     "anomaly_driver_id": integer
#                 }}
#             ]

#             Only return a maximum of  results 3, high quality results. If no anomalous data is found, return an empty list: `[]`
            
#             Return only the raw array. No code blocks, no explanations, no additional formatting.
#             """)

#         print(llm_response.text)
#         formatted_result = self.process_llm_response(llm_response.text, 1)
#         # print(formatted_result)
#         if formatted_result:
#             return formatted_result
#         else:
#             return None


# ######################################################################################
#     def verify_missing_fuel(self):

#         historical_context = {'day_data': {}, 'fuel_invoices': {}}
        
#         for fuel in Fuel.query.all():
#             fuel_invoice = {
#                 column.name: getattr(fuel, column.name) 
#                 for column in Fuel.__table__.columns
#             }
#             historical_context['fuel_invoices'][fuel.id] = fuel_invoice
#             historical_context['fuel_invoices'][fuel.id]['truck_registration'] = fuel.truck.registration
        
#         # pprint(historical_context)

#         for day in Day.query.filter(Day.date<=datetime.date(2024, 11, 1)).all():
#             day_data = {
#                 column.name: getattr(day, column.name)
#                 for column in Day.__table__.columns
#             }
#             historical_context['day_data'][day.id] = day_data
#             if day.truck:
#                 historical_context['day_data'][day.id]['truck_registration'] = day.truck.registration

#         # pprint(historical_context)

#         feedback = {26/11/2024: 
#                         [{"anomaly_date": "16/09/2024", "day_of_week": "Monday",
#                         "anomaly_truck_registration": "CE21 HFD", "anomaly_truck_id": 2, "helpful": True},
#                         {"anomaly_date": "16/09/2024", "day_of_week": "Monday", 
#                         "anomaly_truck_registration": "CA68 OXN", "anomaly_truck_id": 1, "helpful": True},
#                         {"anomaly_date": "18/09/2024", "day_of_week": "Wednesday",
#                         "anomaly_truck_registration": "CE24 FJV", "anomaly_truck_id": 3, "helpful": False},
#                         {"anomaly_date": "19/09/2024", "day_of_week": "Thursday",
#                         "anomaly_truck_registration": "CE21 HFD", "anomaly_truck_id": 2, "helpful": False},
#                         {"anomaly_date": "19/09/2024", "day_of_week": "Thursday",
#                         "anomaly_truck_registration": "CA68 OXN", "anomaly_truck_id": 1, "helpful": False},],
#         27/11/2024 :
#                         [{'anomaly_date': '16/09/2024', 'day_of_week': 'Monday',
#                         'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': True}, 
#                         {'anomaly_date': '16/09/2024', 'day_of_week': 'Monday', 
#                         'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
#                         {'anomaly_date': '18/09/2024', 'day_of_week': 'Wednesday', 
#                         'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': True}, 
#                         {'anomaly_date': '26/09/2024', 'day_of_week': 'Thursday', 
#                         'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': False},],
#         28/11/2024: 
#             [
#                 {'anomaly_date': '24/09/2024', 'day_of_week': 'Tuesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
#                 {'anomaly_date': '26/09/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}, 
#                 {'anomaly_date': '27/09/2024', 'day_of_week': 'Friday', 'anomaly_truck_registration': 'CE21 HFD', 'anomaly_truck_id': 2, 'helpful': True}, 
#                 {'anomaly_date': '30/09/2024', 'day_of_week': 'Monday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}, 
#                 {'anomaly_date': '01/10/2024', 'day_of_week': 'Tuesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
#                 {'anomaly_date': '03/10/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
#                 {'anomaly_date': '03/10/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CE24 FJV', 'anomaly_truck_id': 3, 'helpful': False}, 
#                 {'anomaly_date': '08/10/2024', 'day_of_week': 'Tuesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': True}, 
#                 {'anomaly_date': '09/10/2024', 'day_of_week': 'Wednesday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}, 
#                 {'anomaly_date': '09/10/2024', 'day_of_week': 'Wednesday', 'anomaly_truck_registration': 'CE24 FJV', 'anomaly_truck_id': 3, 'helpful': False}, 
#                 {'anomaly_date': '10/10/2024', 'day_of_week': 'Thursday', 'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, 'helpful': False}
#                 ]}

# #   ai pred.      ("[{'anomaly_date': '16/09/2024', 'anomaly_truck_registration': 'CE21 HFD', "
# #  "'anomaly_truck_id': 2, 'explanation': 'Fuel marked as purchased in day entry "
# #  "but no corresponding fuel entry found.'}, {'anomaly_date': '16/09/2024', "
# #  "'anomaly_truck_registration': 'CA68 OXN', 'anomaly_truck_id': 1, "
# #  "'explanation': 'Fuel marked as purchased in day entry but no corresponding "
# #  "fuel entry found.'}, {'anomaly_date': '16/09/2024', "
# #  "'anomaly_truck_registration': 'CE24 FJV', 'anomaly_truck_id': 3, "
# #  "'explanation': 'Fuel marked as purchased in day entry but no corresponding "
# #  "fuel entry found.'}]")
        
#         # Use this feedback from the user: {feedback}
#         # For each `day_entry` where `fuel` is True (meaning fuel was supposedly purchased) *and* the date is before 01/11/2024, verify that a corresponding `fuel_entry` exists with the same `truck_id` and `date`.

#         # Conversely, for each `fuel_entry` *before* 01/11/2024, verify that a corresponding `day_entry` exists with `fuel` set to True and the same `truck_id` and `date`.
#         cutoff_date = "1/11/2024"

#         # If a `day_entry` with `fuel = True` has no matching `fuel_entry`, *or* if a `fuel_entry` has no corresponding `day_entry` with `fuel = True`, then it should be considered anomalous.
#         llm_response = self.model.generate_content(
#         f"""
#         Analyze this historical data for missing fuel invoices. The data is comprised of day entries for each driver/truck, and fuel invoices for each truck: 
        
#         {historical_context}

#         Where fuel=True in a day entry, there should be a corresponding fuel invoice for the same truck and date.

#         Check all of the history systematically and identify any discrepencies in the following format:

#         [
#             {{
#                 "anomaly_date": "DD/MM/YYYY",
#                 "anomaly_truck_registration": "CA68 OXN",
#                 "explanation": State whether a fuel entry is missing for a day entry with fuel=True, or a day entry with fuel=True is missing for a fuel entry.
#             }}
#         ]

#         If no anomalous data is found, return an empty list: `[]`

#         Return only the raw array. No code blocks, no explanations, no additional formatting.
#         """
#         )
        
#             # f""""
#             # Analyze this historical data for patterns and anomalies: {historical_context}
            
#             # Format your response as a comma-separated list of ONLY the Day IDs that are anomalous.
#             # Example format: 1,4,7
            
#             # Do not include any other text or explanation
#             # """)

#         pprint(llm_response.text)
#         return llm_response.text

#         # formatted_result = self.process_llm_response(llm_response.text, 1)
#         # print(formatted_result)
#         # if formatted_result:
#         #     return formatted_result
#         # else:
#         #     return None
        
#     # def _get_historical_data(self, driver):
#     #     # Get last 30 days of earnings for this driver
#     #     history = DayEnd.query.filter_by(driver_id=driver.id).order_by(DayEnd.date.desc()).limit(30).all()
#     #     return "\n".join([
#     #         f"Date: {entry.date}, Earnings: £{entry.total_earned}"
#     #         for entry in history
#     #     ])
        
#     # def _get_feedback_patterns(self):
#     #     # Get verified patterns from feedback
#     #     helpful_feedback = VerificationFeedback.query.filter_by(was_helpful=True).all()
#     #     return "\n".join([
#     #         f"Verified pattern: {feedback.verification_data}"
#     #         for feedback in helpful_feedback
#     #     ])

#         for payslip in Payslip.query.all():
#             payslip_data = {
#                 column.name: getattr(payslip, column.name)
#                 for column in Payslip.__table__.columns
#             }


# from flask import jsonify, request  # Import necessary modules

# # ... other imports

# # @verification_bp.route('/verification-feedback/<int:formatted_anomaly_id>', methods=['POST'])
# # def create_verification_feedback(formatted_anomaly_id):
# #     """Creates VerificationFeedback for a given FormattedAnomaly."""
# #     formatted_anomaly = FormattedAnomoly.query.get_or_404(formatted_anomaly_id)

# #     is_helpful = request.form.get('is_helpful')

# #     feedback = VerificationFeedback(
# #         user_confirmed_alomaly=user_confirmed,
# #         ai_response_id=ai_response_id,
# #         formatted_anomaly_id=formatted_anomaly_id
# #     )

# #     db.session.add(feedback)
# #     db.session.commit()

# #     return jsonify({
# #         'status': 'success',
# #         'feedback_id': feedback.id
# #     }), 201
