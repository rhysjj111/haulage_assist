import json
import logging
from haulage_app import db
from haulage_app.utilities.gemini_utils import Gemini, genai
import typing_extensions as typing
from typing import Literal
from haulage_app.verification.models import AiRawResponse, MissingEntrySuggestion, TableName, DayAnomalySuggestion
from haulage_app.models import Driver, Day, Fuel, Job, Payslip, Truck
from haulage_app.functions import query_to_dict, date_to_db, is_within_acceptable_date_range
from pprint import pprint

class MissingDriverEntry(typing.TypedDict):
    driver_id: int
    missing_dates: list[str]

class MissingTruckEntry(typing.TypedDict):
    truck_id: int
    missing_dates: list[str]

class AnomalousDateEntry(typing.TypedDict):
    date: str
    explanation: str

class AnomalousTruckEntry(typing.TypedDict):
    truck_id: int
    anomalous_dates: list[AnomalousDateEntry]


class GeminiVerifier(Gemini):
    def __init__(self, model_name=None):
        super().__init__(model_name)

    def _store_initial_response(self, llm_response, prompt, historical_context):
        """
        Stores the raw response from the LLM.

        Args:
            llm_response (str): The raw JSON response from the LLM.
            historical_context (str): The historical context used for the LLM prompt.
        """
        try:
            ai_response_entry = AiRawResponse(
                prompt = prompt,
                raw_response = llm_response,
                historical_context_json = historical_context
            )
            db.session.add(ai_response_entry)
            db.session.commit()
        except Exception as e:
            logging.exception(
                f"Error commiting to AiResponse: {e},"                
            )
            db.session.rollback()
        else:
            print(f"Successfully added response: {ai_response_entry_id} to AiResponse")
            return ai_response_entry.id

    def _jsonify_llm_response(self, llm_response, collection=True):    
        # Remove triple quotes and parse json response
        llm_response = llm_response.replace('```', '')
        llm_response = llm_response.replace('json','')
        llm_response = llm_response.replace("'",'"')
        anomalous_data_predictions = json.loads(llm_response.strip())
        # Validate it's a list
        if collection:
            if not isinstance(anomalous_data_predictions, list):
                raise ValueError("Response is not a list format")
        return anomalous_data_predictions

    def llm_detect_anomalous_mileage(self):
        """
        Detect anomalous mileage for trucks.
        """
        historical_context = {}
        query_to_dict(
            historical_context, 
            Day, 
            filter_criteria=(Day.status == 'working', 
                Day.start_mileage > 0,
                Day.end_mileage > 0,
            ), 
            relevant_attributes=['id', 'date', 'truck_id', 'start_mileage', 'end_mileage'])

        # prompt = f"""
        # Act as a data analyst flagging potential mileage data anomalies to a collegue who will investigate your suggestions.

        # You are given data retrieved from a database in JSON format. 
        # The data represents mileage records with the following structure for each entry:
        # {{
        #     "day_id": 1,
        #     "date": "YYYY-MM-DD", 
        #     "truck_id": 1,
        #     "start_mileage": 12345, 
        #     "end_mileage": 12500,
        # }}

        # Key definitions:
        # - `day_id`: Unique identifier for each day entry.
        # - `date`: Date of the day entry.
        # - `truck_id`: Unique identifier for each truck.
        # - `start_mileage`: Starting mileage of the day entry.
        # - `end_mileage`: Ending mileage of the day entry.

        # There may be missing day_id values (due to deletions or filtered data).

        # Here is the JSON data: 

        # {historical_context}

        # Process the data with these steps:

        # 1. Begin by isolating data for truck 1.
        # 1. Order the day entries by date.
        # 2. For each consecutive date pair in the ordered list, compare the `end_mileage` of the first entry with the `start_mileage` of the second entry.
        # 3. Return a list of any date pairs where the `end_mileage` and `start_mileage` values do not match.
        # 4. Display your findings in a short, concise sentence for each anomalous date pair, 
        #     including any data that will aid in identifying and assessing the suggestion, such as dates, mileages and any explanations.
        # 5. After analyzing truck 1, repeat steps 1-4 for each of the remaining trucks in the dataset.


        # """

        prompt = f"""
        Act as a data analyst/engineer presenting data for a small haulage company.
        Keep your answer short and data centric.
        The day_data represents a collection of days, each day entry represents an entry from a driver's log.

        i. Data:
        {historical_context}

        ii.Overview:
        Focus on the mileages. 
        Each end_mileage of one day, should have the same value as the start_mileage of the next working day.
        This is because the truck won't be driven if it's not working.
        The mileage may change over the weekend if it is used and not logged.
        

        iii.Follow the below instructions:
        
        1. Extract all the entries with truck_id of 1.

        2. Put the entries in order of date.

        2. Make a note of any entries that seem anomalous.

        3. Make a note of any pairs of entries of adjacent dates that seem anomalous.

        3. List your findings, and explain why you think they are anomalous.
        In your explanation, include any important information for tracking down the entry such as date, truck_id, day_id etc.
        Seperate your findings into two parts:
            - Data comparison/display
            - 'Verbal' explanation

        """
        llm_response = self.generate_response(prompt,0)


        print(f"LLM RESPONSE", llm_response)
        # truck_1_entries = []
        # for entry in historical_context['day_data']:
        #     if entry['truck_id'] == 1:
        #         pprint(entry)

        # 4. Format each anomalous suggestion in a short paragraph, which will be displayed back to the user, 
        # so that they can easily undertand and attempt to verify and correct the anomaly. 
        # Include an assesment of the chances that a suggestion is actually and anomaly.
        # 5. Repeat steps 1-4 for all truck_id's.

        format_prompt = f"""
        Below is workings out for detecting dates with anomolous mileages.

        Focus on the output section.

        Extract a list of anomalous dates, with their explanations, and the truck_id.

        Return only the raw array. No code blocks, no explanations, no additional formatting.

        Information:
        {llm_response}
        """
        # formatted_llm_response = self.generate_response_json(
        #     format_prompt,
        #     list[AnomalousTruckEntry],
        #     0
        # )
        # print(formatted_llm_response)
        # formatted_llm_response = self._jsonify_llm_response(formatted_llm_response, False)
        # formatted_llm_response_collection.append(formatted_llm_response)

    # print("COMBINED RESPONSE:", formatted_llm_response_collection)

        prompt = f"""
        Act as a data analyst/engineer presenting data for a small haulage company.
        Keep your answer short and data centric.
        The day_data represents a collection of days, each day entry represents an entry from a driver's log.
        Focus on the mileages. 
        Each end_mileage of one day, should have the same value as the start_mileage of the next.
        
        i. Data:
        {historical_context}

        Follow the below instructions:
        
        1. Extract all the entries with truck_id of 1.

        2. Put the entries in order of date.

        2. For each entry (except the last), check that the end_mileage is the same as the start_mileage of the next day.

        3. Create a list of anomalous pairs of entries, along with any important information such as truck_id and date.

        4. Format the answer to display back to a user, in paragraph form, so that they can easily undertand and attempt to verify and correct the anomaly.

        5. Repeat steps 1-4 for all truck_id's.

        """



    def llm_detect_missing_fuel_invoices(self):
        day_historical_context = {}
        fuel_historical_context = {}
        query_to_dict(fuel_historical_context, Fuel, relevant_attributes=['date', 'truck_id'])
        query_to_dict(day_historical_context, Day, filter_criteria=(Day.fuel == True,),  relevant_attributes=['date', 'truck_id'])
        historical_context = {
            **day_historical_context,
            **fuel_historical_context
        }
        prompt = f"""
        Act as a data analyst/engineer presenting data for a small haulage company.
        The company has 3 trucks.
        The day_data represents days from a driver log where they recorded getting fuel in a particular truck.
        The fuel_data represents the invoices for fuel.
        Follow the below instructions in order:

        i. Here is the day data:
        {day_historical_context}

        1. Create a list of dates for the truck with id of 1 has marked as getting fuel, and order in ascending order.

        ii. Here is the fuel data:
        {fuel_historical_context}

        2. Create a list of dates the truck with id of 1 has fuel invoices recorded, and order in ascending order.        

        3. Finally, list the dates that are expected but not present (missing_dates) in the list for truck 1.
        (When labeling the missing dates, please indicate the truck id. ie. 'Truck_1 Missing Dates: [date1, date2, ...]')

        4. Repear steps 1-3 for the other two trucks.

        """
        llm_response= self.generate_response(prompt,0)
        print("LLM RESPONSE:", llm_response)
        format_prompt = f"""
        Below is workings out for detecting missing fuel invoices for trucks.

        Focus on the output section.

        Extract a list of missing dates for each truck.

        Return only the raw array. No code blocks, no explanations, no additional formatting.

        llm response:
        {llm_response}
        """
        # print("FUEL INVOICES LLM RESPONSE:", llm_response)
        # formatted_llm_response = self.generate_response(
        #     format_prompt,
        #     0
        # )
        # formatted_llm_response = self.generate_response_json(
        #     format_prompt,
        #     list[MissingTruckEntry],
        #     0
        # )
        # print(formatted_llm_response)
        # self.process_llm_anomalous_data_suggestions(formatted_llm_response, prompt, historical_context, "fuel")


    def llm_detect_missing_payslips(self):
        historical_context = {}
        query_to_dict(historical_context, Payslip, relevant_attributes=['id', 'date', 'driver_id'])

        prompt = f"""
        Act as a data analyst/engineer.
        You are cleaning data for a haulage company based in the UK.
        The company has 3 drivers and below is a list of dictionaries of their payslips.
        The drivers get paid weekly, typically on a Friday, but may get paid on a Thursday for bank holidays.
        There should only be one payslip per driver, per week.
        A week is defined as Saturday to Friday.

        i. Here is the payslip data:
        {historical_context}

        Please complete the below instructions:

        1. Create a list of expected dates that payslips should exist.

        2. Extract a list of dates from the payslip data (i) for the driver with id of 1

        3. Finally, list the dates that are expected but not present (missing_dates) in the list for driver 1.
        (When labeling the missing dates, please indicate the truck id. ie. 'Truck_1 Missing Dates: [date1, date2, ...]')

        4. Repeat steps 2-3 for the remaining drivers.
        """

        llm_response = self.generate_response(prompt, 0)
        print('initial llm response successful.')
        # ai_response_id = self._store_initial_response(llm_response, prompt, historical_context)

        format_prompt = f"""
        Below is workings out for detecting missing payslips for drivers.

        Focus on the output section.

        Extract a list of missing dates for each driver.

        Return only the raw array. No code blocks, no explanations, no additional formatting.

        llm response:
        {llm_response}
        """ 

        formatted_llm_response = self.generate_response_json(
            format_prompt,
            list[MissingDriverEntry],
            0
        )
        print('llm_response_format_successful.')
        print(formatted_llm_response)
        # self._process_llm_anomalous_data_suggestions(formatted_llm_response, ai_response_id, "payslip")

    def _process_llm_anomalous_data_suggestions(self, formatted_llm_response, ai_response_id, table_name):
            anomalous_data_predictions = self._jsonify_llm_response(formatted_llm_response)

            try:
                self._process_individual_suggestions(
                    anomalous_data_predictions,
                    ai_response_entry_id,
                    table_name
                )
                    
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logging.exception(f"Error processing LLM response: {e}, Response: {llm_response}, "
                                f"Historical context:")
                db.session.rollback()
            except Exception as e:
                logging.exception(f"An unexpected error occurred: {e}, Response: \
                    {llm_response}, Historical context: ")
                db.session.rollback()
            else:
                print("Successfully added raw ai response and processed responses.")
    

    def _process_individual_suggestions(self, anomalous_data_predictions, ai_response_entry_id, table_name):
        """
        Helper function to process the missing data predictions from the LLM response.

        Args:
            anomalous_data_predictions (list): List of predictions for missing data.
            ai_response_entry_id (int): ID of the AI response entry.
            table_name (str): Name of the table to process.
        """
        model_map = {'fuel': Fuel, 'day': Day, 'payslip': Payslip}
        table_name_enum_map = {
            'fuel': TableName.FUEL, 
            'day': TableName.DAY,
            'payslip': TableName.PAYSLIP
        }
        anomaly_model_map = {'day': DayAnomalySuggestion}
        suggested_entries = []
        table_model = model_map[table_name]

        for entry in anomalous_data_predictions:
            anomaly_id = entry.get('driver_id') or entry['truck_id']
            anomaly_identifier = 'driver_id' if 'driver_id' in entry else 'truck_id'
            
            if 'missing_dates' in entry:
                # Process each missing_entry
                for date in entry['missing_dates']:
                    anomaly_date = date_to_db(date)

                    # Check if an entry with the same ID and date already exists
                    existing_entry = MissingEntrySuggestion.query.filter(
                        getattr(MissingEntrySuggestion, anomaly_identifier) == anomaly_id,
                        MissingEntrySuggestion.date == anomaly_date,
                        MissingEntrySuggestion.ai_response_feedback == None
                    ).order_by(MissingEntrySuggestion.id.desc()).first()

                    if existing_entry:
                        print(f"Entry already exists for {anomaly_identifier}: {anomaly_id} on {anomaly_date}")
                        continue  # Skip to the next iteration

                    # Create new database entry
                    suggested_entry = MissingEntrySuggestion(
                        ai_raw_response_id = ai_response_entry_id,
                        date = anomaly_date,
                        table_name = table_name_enum_map[table_name],
                        type = 'missing_entry',
                        confirmed_missing_date = None,
                        driver_id=None, 
                        truck_id=None 
                    )

                    # Set the appropriate ID (driver_id or truck_id) based on anomaly_identifier
                    setattr(suggested_entry, anomaly_identifier, anomaly_id)

                    # Check if missing entry exists
                    entry_check = table_model.query.filter(
                        getattr(table_model, anomaly_identifier) == anomaly_id,
                        table_model.date == anomaly_date
                    ).first() 

                    # --- Special Cases ---                                            
                    if table_name == "fuel":
                        # Check if fuel_tag is true in Day table
                        fuel_tag_true = Day.query.filter(
                            Day.truck_id == anomaly_id,
                            Day.date == anomaly_date,
                            Day.fuel == True
                        ).first()
                        if not fuel_tag_true:
                            entry_check = None
                    elif table_name == "day":
                        if anomaly_date.weekday() in (5, 6): # Saturday or Sunday
                            entry_check = None
                    # --- End of Special Cases ---

                    suggested_entry.confirmed_missing_date = entry_check is None # True if no entry exists, False if an entry exists.
                    suggested_entries.append(suggested_entry)
                    print('new entry appended')
            elif 'anomalous_dates' in entry:
                # Process each anomalous_date
                anomaly_model = anomaly_model_map[table_name]
                for nested_entry in entry['anomalous_dates']:

                    anomaly_date = date_to_db(nested_entry['date'])
                    anomaly_explanation = nested_entry['explanation']
                    # Check if actual instance exists
                    anomaly_instance = table_model.query.filter(
                        getattr(table_model, anomaly_identifier) == anomaly_id,
                        table_model.date == anomaly_date
                    ).first()
                    if not anomaly_instance:
                        print(f"Actual anomaly does not exist for {table_name}: {anomaly_identifier}, {anomaly_id} on {anomaly_date}")
                        continue
                    day_id = anomaly_instance.id
                    # Check if the suggested anomaly already exists
                    existing_entry = anomaly_model.query.filter(
                        anomaly_model.id == day_id,
                        anomaly_model.ai_response_feedback == None
                    ).order_by(anomaly_model.id.desc()).first()
                    if existing_entry:
                        print(f"Anomaly suggestion already exists for {anomaly_identifier}: {anomaly_id} on {anomaly_date}")
                        continue  # Skip to the next iteration
                    # Create new database entry
                    suggested_entry = anomaly_model(
                        ai_raw_response_id = ai_response_entry_id,
                        table_id = day_id,
                        date = anomaly_date,
                        type = f"{table_name}_anomaly",
                        explanation = anomaly_explanation,
                    )

    ## NOTE TO SELF: ANOMALOUS SUGGESTION AND MISSING SUGGESTION BOTH REQUIRE A CHECK THAT THE SUGGESTED ENTRY IS 
    ## IN THE DATABASE (OR NOT FOR MISSING SUGGESTION).
    ## THEY ALSO REQUIRE A SEARCH FOR THE SAME SUGGESTION WITHIN THE ANOMALY DATABASE.
    ## THERE ARE EXTRA CHECKS (SPECIAL CASES) FOR MISSING SUGGESTIONS BUT THESE COULD BE REDUNDANT AND LEFT UP TO THE USER.

                

        # Add to database
        db.session.add_all(suggested_entries)
        db.session.commit()

        # """
        # Processes an LLM response for missing data, saves the raw response, and generates suggestions.

        # Args:
        #     llm_response (str): The raw JSON response from the LLM.
        #     historical_context (str): The historical context used for the LLM prompt.
        #     table_name (str): Name of the table to process ('fuel', 'day', or 'payslip').

        # Returns:
        #     bool: True if the processing was successful, False otherwise.
        # """
        # try:
        #     ai_response_entry = AiRawResponse(
        #         prompt = prompt,
        #         raw_response = llm_response,
        #         historical_context_json = historical_context
        #     )
        #     db.session.add(ai_response_entry)
        #     db.session.commit()
        # except Exception as e:
        #     logging.exception(
        #         f"Error commiting to AiResponse: {e},"                
        #     )
        #     db.session.rollback()
        # else:



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
