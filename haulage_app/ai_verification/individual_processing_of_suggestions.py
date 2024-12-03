def process_llm_missing_data_response(self, llm_response, historical_context, Table):
    try:
        ai_response_entry = RawResponse(raw_response=llm_response, historical_context=historical_context)
        db.session.add(ai_response_entry)
        db.session.commit()
        response_id = ai_response_entry.id
        logging.info(f"Successfully added response: {response_id} to RawResponse")

        missing_entries = json.loads(llm_response.strip())

        if not isinstance(missing_entries, list):
            raise ValueError("LLM response is not a list")

        new_entries = []
        all_suggestions_helpful = True

        # Limit to 3 suggestions (adjust as needed)
        for entry in missing_entries[:3]:
            try:
                anomaly_date = date_to_db(entry['anomaly_date'])
                driver_id = entry['anomaly_identifier_id']  # Or appropriate identifier
                new_entry = MissingEntry(
                    ai_response_id=response_id,
                    date=anomaly_date,
                    driver_id=driver_id,
                    table_name=TableName[Table.__name__.upper()],
                    processing_successful=True  # Assume success initially
                )

                # Check for existing entry or repeat: This logic is unchanged.
                existing_record = Table.query.filter(
                    Table.driver_id == driver_id,
                    Table.date == anomaly_date
                ).first()
                repeated_record = MissingEntry.query.filter(
                    MissingEntry.driver_id == driver_id,
                    MissingEntry.date == anomaly_date
                ).first()
                if existing_record:
                    new_entry.suggestion_exists = True
                    all_suggestions_helpful = False
                if repeated_record:
                    new_entry.suggestion_repeated = True
                    all_suggestions_helpful = False

                db.session.add(new_entry)

            except (KeyError, ValueError, TypeError) as e:
                all_suggestions_helpful = False
                new_entry.processing_successful = False
                new_entry.error_message = str(e)  # Store error message
                db.session.add(new_entry)
                logging.exception(f"Error processing suggestion: {entry}, Error: {e}")
            except Exception as e:
                all_suggestions_helpful = False
                new_entry.processing_successful = False
                new_entry.error_message = str(e)
                db.session.add(new_entry)
                logging.exception(f"Unexpected error processing suggestion: {entry}, Error: {e}")

        ai_response_entry.all_suggestions_helpful = all_suggestions_helpful
        db.session.commit()
        return True
    except Exception as e:
        logging.exception(f"An unexpected error occurred: {e}")
        db.session.rollback()
        return False

########### method 2

    def process_llm_missing_data_response(self, llm_response, historical_data, table):
        try:
            ai_response_entry = RawResponse(raw_response=llm_response, historical_context=historical_data)
            db.session.add(ai_response_entry)
            db.session.commit()
            response_id = ai_response_entry.id
            logging.info(f"Successfully added response: {response_id} to RawResponse")

            missing_data_predictions = json.loads(llm_response.strip())

            if not isinstance(missing_data_predictions, list):
                raise ValueError("LLM response is not a list")

            suggested_entries = []
            all_suggestions_helpful = True

            for prediction in missing_data_predictions:
                try:
                    anomaly_date = date_to_db(prediction['anomaly_date'])
                    driver_id = prediction['anomaly_identifier_id']
                except (KeyError, ValueError) as e:
                    all_suggestions_helpful = False
                    logging.exception(f"Invalid data format in LLM response: {e}")
                    continue  # Skip this invalid prediction

                new_entry = MissingEntry(ai_response_id=response_id, date=anomaly_date, driver_id=driver_id, table_name=table.value) # table.value

                # Check if already exists
                if table.query.filter(table.driver_id == driver_id, table.date == anomaly_date).first():
                    new_entry.suggestion_exists = True
                    all_suggestions_helpful = False


                suggested_entries.append(new_entry)

            db.session.add_all(suggested_entries)
            ai_response_entry.all_suggestions_helpful = all_suggestions_helpful # Update helpful flag.
            db.session.commit()
            logging.info("Successfully processed LLM response")
            return True

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logging.exception(f"Error processing LLM response: {e}")
            db.session.rollback() # Rollback in case of errors.
            ai_response_entry.processing_successful = False  # Update processing status flag.
            db.session.commit() # This commit ensures the error state is persisted.
            return False
        except Exception as e:
            logging.exception(f"An unexpected error occurred: {e}")
            db.session.rollback()
            ai_response_entry.processing_successful = False
            db.session.commit()
            return False
