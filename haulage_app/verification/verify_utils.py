from haulage_app.utilities.gemini_utils import Gemini, genai
import typing_extensions as typing
# from haulage_app.verification.models import AiRawResponse, MissingEntrySuggestion, TableName
from haulage_app.models import Driver, Day, Fuel, Job, Payslip, Truck
from haulage_app.functions import query_to_dict, date_to_db, is_within_acceptable_date_range

class MissingDriverEntry(typing.TypedDict):
    driver_id: int
    missing_dates: list[str]

class GeminiVerifier(Gemini):
    def __init__(self, model_name=None):
        super().__init__(model_name)

    def llm_detect_missing_payslips(self, start_date, end_date):
        historical_context = {}
        query_to_dict(historical_context, Payslip, relevant_attributes=['id', 'date', 'driver_id'])
        prompt = f"""
        Act as a data analyst/engineer.
        You are cleaning data for a haulage company based in the UK.
        The company has 3 drivers and below is a list of dictionaries of their payslips.
        The drivers get paid weekly, typically on a Friday, but may get paid on a Thursday for bank holidays.
        There should only be one payslip per driver, per week.
        The dates of the data span {start_date} to {end_date}.
        A week is defined as Saturday to Friday.

        i. Here is the payslip data:
        {historical_context}

        Please complete the below instructions:

        1. Create a list of expected dates that payslips should exist.

        2. Extract a list of dates from the payslip data (i) for the driver with id of 1

        3. Finally, list the dates that are expected but not present (missing_dates) in the list for driver 1.

        4. Repeat steps 2-3 for the remaining drivers.
        """

        llm_response = self.generate_response(prompt, 0)
        print(llm_response)

        format_prompt = f"""
        Please extract the driver_id and corresponding missing dates for the drivers.

        Only return the JSON, no additional text, no additional explanation.

        {llm_response}
        """    
        formatted_llm_response = self.model.generate_content(
            format_prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0,
                response_mime_type="application/json", response_schema=list[MissingDriverEntry])
        )
        print(formatted_llm_response.text)

        return llm_response, historical_context

    def process_llm_missing_data(self, llm_response, historical_context):
            try:
                historical_context_string = f"{historical_context}"
                ai_response_entry = AiRawResponse(
                    raw_response = llm_response,
                    historical_context_string = historical_context_string
                )
                db.session.add(ai_response_entry)
                db.session.commit()
            except Exception as e:
                logging.exception(
                    f"Error commiting to AiResponse: {e},"
                    #      Response: {llm_response}, \
                    # Historical context: {historical_context}"
                    
                )
                db.session.rollback()
                return False
            else:
                ai_response_entry_id = ai_response_entry.id
                print(f"Successfully added response: {ai_response_entry_id} to AiResponse")

                try:
                    # Remove triple quotes
                    llm_response = llm_response.replace('```', '')
                    llm_response = llm_response.replace('json','')
                    llm_response = llm_response.replace("'",'"')
                    # Parse the JSON response
                    missing_data_predictions = json.loads(llm_response.strip())

                    # Validate it's a list
                    if not isinstance(missing_data_predictions, list):
                        raise ValueError("Response is not a list format")

                    suggested_entries = []

                    model_map = {'fuel': Fuel, 'day': Day, 'payslip': Payslip}
                    table_name_map = {'fuel': TableName.FUEL, 'day': TableName.DAY, 'payslip': TableName.PAYSLIP}

                    # Process each missing_entry
                    for entry in missing_data_predictions:
                        # Create new database entry
                        anomaly_date = date_to_db(entry['anomaly_date'])
                        anomaly_id = entry['anomaly_identifier_id']
                        start_date = datetime.date(2024,9,20)
                        table_data = entry['from_dictionary']
                        table_name = table_data.replace("_data", "")
                        suggested_entry = MissingEntrySuggestion(
                            raw_response_id = ai_response_entry.id,
                            date = anomaly_date,
                            table_name = table_name_map.get(table_name),
                            type = 'missing_entry',
                            date_range_acceptable = None,
                            valid_suggestion = None,
                            original_suggestion = None
                        )
                        anomaly_identifier = entry['anomaly_identifier']
                        if anomaly_identifier == "truck_id":
                            suggested_entry.truck_id = anomaly_id
                        else:
                            suggested_entry.driver_id = anomaly_id
                        # Check if suggestion date is within acceptable range
                        if not is_within_acceptable_date_range(anomaly_date, start_date):
                            suggested_entry.date_range_acceptable = False
                        else:
                            suggested_entry.date_range_acceptable = True
                            # Check if missing entry exists
                            table_model = model_map[table_name]
                            if anomaly_identifier == "truck_id":
                                invalid_suggestion = table_model.query.filter(
                                    table_model.truck_id == anomaly_id,
                                    table_model.date == anomaly_date
                                ).first()
                                if table_name == "fuel":
                                    fuel_tag_true = Day.query.filter(
                                        Day.truck_id == anomaly_id,
                                        Day.date == anomaly_date,
                                        Day.fuel == True
                                    ).first()
                                    if not fuel_tag_true:
                                        invalid_suggestion = True
                            else:
                                if table_name == "fuel":
                                    continue
                                invalid_suggestion = table_model.query.filter(
                                    table_model.driver_id == anomaly_id,
                                    table_model.date == anomaly_date
                                ).first()
                                if table_name == "day":
                                    if anomaly_date.weekday() == 5 or anomaly_date.weekday() == 6:
                                        invalid_suggestion = True
                            if invalid_suggestion:
                                suggested_entry.valid_suggestion = False
                            else:
                                suggested_entry.valid_suggestion = True
                                # Check if missing entry is repeated
                                repeated_record = MissingEntrySuggestion.query.filter(
                                    MissingEntrySuggestion.driver_id == anomaly_id,
                                    MissingEntrySuggestion.date == anomaly_date
                                ).first()
                                if repeated_record:
                                    suggested_entry.original_suggestion = False
                                else:
                                    suggested_entry.original_suggestion = True
                        suggested_entries.append(suggested_entry)
                        print('new entry appended')
                        # Add to database
                    db.session.add_all(suggested_entries)
                    db.session.commit()
                        
                except json.JSONDecodeError:
                    logging.exception(f"Invalid JSON received from LLM: \
                        {llm_response}, Historical context: ")
                    db.session.rollback()
                    ai_response_entry.processing_successful = False
                    db.session.commit()
                    return False
                except KeyError as e:
                    logging.exception(f"Missing key in JSON response: {e}, Response: \
                        {llm_response}, Historical context: ")
                    db.session.rollback()
                    ai_response_entry.processing_successful = False
                    db.session.commit()
                    return False
                except ValueError as e:
                    logging.exception(f"Invalid data format: {e}, Response: \
                        {llm_response}, Historical context: ")
                    db.session.rollback()
                    ai_response_entry.processing_successful = False
                    db.session.commit()
                    return False
                except Exception as e:
                    logging.exception(f"An unexpected error occurred: {e}, Response: \
                        {llm_response}, Historical context: ")
                    db.session.rollback()
                    ai_response_entry.processing_successful = False
                    db.session.commit()
                    return False
                else:
                    print("Successfully added raw ai response and processed responses.")
                    return True





############# NOTES......................................................
# prompt = f"""
# You are a data analysis, cleaning up some data.
# Below is a sample of dates.
# The sample data should have a date for every Friday between 2024-09-20 and 2024-12-20, inclusive.

# i. sample data:
# {historical_context}

# Follow the below steps to calculate the missing dates.

# 1. Create a list of expected dates that payslips should exist between 2024-09-20 and 2024-12-20, inclusive. Put them in acending order.

# 2. Extract a list of dates from the sample data (i), put them in ascending order.

# 3. Finally, list the dates that are expected but not present in the extracted list.
# """
# prompt = f"""
# Act as a data analyst/engineer.
# You are cleaning data for a haulage company based in the UK.
# The company has 3 drivers and below is a list of dictionaries of their payslips.
# The drivers get paid weekly, typically on a Friday, but may get paid on a Thursday for bank holidays.
# The dates of the data span 2024-09-20 to 2024-12-20.
# A week is defined as Saturday to Friday.

# i. Here is the payslip data:
# {historical_context}

# Please complete the below instructions:

# 1. Create a list of expected dates that payslips should exist.

# 2. Extract a list of dates from the payslip data (i) for the driver with id of 1.

# 3. Finally, list the dates that are expected but not present (missing_dates) in the list for driver 1.

# 4. Repeat steps 2-3 for the remaining drivers.
# """
# prompt = f"""
# The sample data below is a list of payslips recorded for drivers.
# The drivers get paid weekly, typically on a Friday, but may get paid on a Thursday for bank holidays.
# A week is defined as Saturday to Friday.

# i. sample data:
# {historical_context}

# Please complete the below instructions:

# 1. **Define all possible payslip dates**
# - Create a list of expected dates that payslips should exist, and arrange in ascending order.

# 2. **Define all current driver payslip dates**
# - Extract a list of dates from the payslip data (i) for the driver with id of 1, and arrange in ascending order.

# 3. **Deduce missing payslip dates**
# - Finally, create a list of dates that are expected, but not present, using the lists from steps 1 and 2.

# Return missing payslip date list.

# """
# prompt = f"""
# Act as a data analyst/engineer.

# You are cleaning data for a haulage company based in the UK.
# The company has 3 drivers and below is a list of dictionaries of their payslips.
# The drivers get paid weekly, typically on a Friday, but may get paid on a Thursday for bank holidays.
# The dates of the data span 2024-09-20 to 2024-12-20.
# A week is defined as Saturday to Friday.

# i. Here is the payslip data:
# {historical_context}

# Find the missing payslip data for each driver by following the below instructions:

# 1. Create a list of expected dates that payslips should exist.

# 2. Extract a list of dates from the payslip data (i) for the driver with id of 3.

# 3. Finally, list the dates that are expected but not present in the list for driver 3.

# 4. Repeat steps 2-3 for the remaining drivers.

# List results in JSON format.
# Use this JSON schema:
# Missing = {{
#     "driver_id": int,
#     "missing_pay_dates": [
#         {{
#             "date": str
#         }}
#     ]
# }}
# Return: list[Missing]

# """

















# def dont_use_llm_detect_missing_payslips(self):

#     historical_context = {}
#     # query_to_dict(historical_context, Driver, relevant_attributes=['id', 'first_name', 'last_name'])
#     query_to_dict(historical_context, Payslip, relevant_attributes=['id', 'date', 'driver_id'])
#     query_to_dict(historical_context, Day, relevant_attributes=['id', 'date', 'driver_id', 'truck_id', 'fuel'])
#     query_to_dict(historical_context, Fuel, relevant_attributes=['id', 'date', 'truck_id'])
#     # query_to_dict(historical_context, Truck, relevant_attributes=['id', 'registration'])

#     # print(historical_context)
#     raw_responses = AiRawResponse.query.all()
#     previous_answers = []
#     for response in raw_responses:
#         previous_answers.append(response.get_ai_response_missing_entry_suggestions())

#     top_raw_responses = (
#         AiRawResponse.query
#         .join(AiRawResponse.processed_responses)  # Join with the related table
#         .filter(MissingEntrySuggestion.original_suggestion == True)  # Filter for True values
#         .group_by(AiRawResponse.id)  # Group by AiRawResponse ID
#         .order_by(desc(func.count(MissingEntrySuggestion.id)))  # Order by count in descending order
#         .limit(2)
#         .all()
#     )
#     top_previous_answers = []
#     for response in top_raw_responses:
#         top_previous_answers.append(response.get_ai_response_missing_entry_context_and_suggestions())
    

#     # print('PREVIOUS ANSWERS::::::::::', previous_answers)

#         # Read the below instructions. Do not carry them out. Instead, give me a summary of what you think I am asking.
#         # Is there anything confusing or unclear about the instructions?
#         # Act as an llm prompt engineer.
#         # Take a look at the below  instructions. Do not carry them out. Instead, give me a summary of what you think I am asking.
#         # Which bits are helpful, and which are confusing.
#         # Do the previous context and answers make sense?
#         # How would you suggest changing the strategy of using an llm to highlight missing entries for the user?
#     llm_response = self.model.generate_content(
#         f"""

#         Use the below historical context to carry out the tasks in the format requested.
#         You are looking for entries that you think are missing. The aim is to find missing entries, not to edit existing ones.
#         The historical context is data from a haulage company with three drivers and three trucks.
#         A week is defined as Monday to Sunday.
#         The working week is defined as Monday to Friday.

#         The data provided will have the following structure:
#         - It contains three seperate datasets: 'payslip_data', 'day_data', and 'fuel_data'.
#         - The date represents the date of the entry.
#         - driver_id is the unique identifier for each driver.
#         - truck_id is the unique identifier for each truck.
#         - If truck_id is None in a day_data entry, this indicates a holiday or absence and not important for any of the tasks.

#         1. Context:

#         1a. Good examples of previous answers with context:
#         {top_previous_answers}

#         1b. Current historical context:
#         {historical_context}

#         1c. Full list of previous suggestions:
#         {previous_answers}

#         2. Answer format:
#         2a. Please provide your answer as a list of dictionaries in the following format:
#         [
#             {{
#                 "anomaly_date": "YYYY-MM-DD",
#                 "anomaly_identifier": "truck_id" or "driver_id" (must always be truck or driver id),
#                 "anomaly_identifier_id: "1",
#                 "from_dictionary": "..._data"
#             }}
#         ]

#         2b. Return only the raw array. No code blocks, no explanations, no additional formatting.

#         2c. There may be no missing data, if no missing data is found, return 'None'.

#         3. Tasks
#         3a. Check for missing day_data.
#         Information to consider:
#         - Based on the provided historical data; identify any potential missing \
#             entries in the `day_data` dataset.
#         - There should be a `day_data` entry for each driver for each workday (Monday to Friday).
#         - If there are fewer than 5 entries for a driver in a given working week (Monday to Friday), create a separate dictionary \
#             in the output array for each missing entry; the anomoly_date representing each missing day date. \
#         - For example, if there are 3 entries in one week, Monday, Wednesday, Friday, create 2 separate dictionaries, each \
#             representing one missing entry. The dates will be for the missing Tuesday and Thursday.
#         - For task 3a, focus only on the driver and date in `day_data`; the `truck_id` will be used in a later task.

#         3b. Check for missing fuel_data.
#         Information to consider:
#         - Analyze the provided `day_data` and `fuel_data`, and any relevant previous data, to identify any potential missing entries in the `fuel_data` dataset.
#         - The `fuel_data` represents fuel invoices received from the fuel supplier.
#         - In `day_data`, the `fuel_flag` boolean represents whether a driver has marked fuel as purchased for that day.
#         - In any given week (Mon to Fri), and any given truck, there should be an equal amount of fuel_data entries to day_data entries with fuel_flag = True.
#         - If there are less fuel_data entries than fuel_flag = True, for any given week and truck, fuel_data should be conscidered missing, \
#             and can be located by finding the the day_data with fuel_flag=True with no corresponding fuel_data entry.
#         - Do nothing if there are multiple fuel data entries for a given truck and date, this is perfectly fine.
#         - The important thing is to note the missing fuel_data. There can be a fuel_data entry without the corresponding fuel flag, \
#             but not the converse.
#         - Take these steps to complete the task:
#         3bi. For each truck and week, find the number of fuel_data entries.
#         3bii. For each truck and week, find the number of day_data entries with fuel_flag = True.
#         3biii. For each truck and week, find any weeks with less fuel_data entries than fuel_flag = True.
#         3biiii. Within these weeks, look for day_data with fuel_flag = True that do not have a corresponding fuel_data entry.
#         3biiiii. Create a dictionary for each missing fuel_data entry, with the anomoly_date representing the date of the missing fuel_data entry.


#         3c. Check for missing payslip_data.
#         Information to consider:
#         - Based on the provided historical data, identify any potential missing entries in the `payslip_data` dataset.
#         - The `payslip_data` represents payslips benerated by the payroll department.
#         - There should be one payslip_data entry for each driver for each working week (Monday to Friday). \
#         """
#         ,
#     generation_config=genai.types.GenerationConfig(
#         temperature=0,)
#     )

#     # print('LLM RESPONSE::::::::::', llm_response.text)
    
#     return llm_response.text, historical_context
