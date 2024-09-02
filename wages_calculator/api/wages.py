from flask import jsonify, request
from wages_calculator.models import Driver, Day
from wages_calculator.functions import date_to_db
from datetime import timedelta
from . import api  # Import the api blueprint

@api.route('/wages', methods=['GET', 'POST'])
def calculate_wages():
    if request.method == 'POST':
        # Handle POST request (same as before)
        data = request.get_json()

        try:
            date_str = data.get('date')
            driver_id = data.get('driver_id')

            if not date_str or not driver_id:
                return jsonify({'error': 'Missing date or driver_id'}), 400

            start_date = date_to_db(date_str)
            end_date = start_date + timedelta(days=6)

            driver = Driver.query.get_or_404(driver_id)
            day_entries = Day.query.filter(
                Day.driver_id == driver_id,
                Day.date >= start_date,
                Day.date <= end_date
            ).all()

            # ... (Perform your wages calculations here) ...

            response_data = {
                # ... (Your response data as before) ...
            }

            return jsonify(response_data)

        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    elif request.method == 'GET':
        # Handle GET request (similar to your previous GET implementation)
        date_str = request.args.get('date')
        driver_id = request.args.get('driver_id')

        try:
            if not date_str or not driver_id:
                return jsonify({'error': 'Missing date or driver_id'}), 400

            start_date = date_to_db(date_str)
            end_date = start_date + timedelta(days=6)

            driver = Driver.query.get_or_404(driver_id)
            day_entries = Day.query.filter(
                Day.driver_id == driver_id,
                Day.date >= start_date,
                Day.date <= end_date
            ).all()

            # ... (Perform your wages calculations here) ...

            response_data = {
                # ... (Your response data as before) ...
            }

            return jsonify(response_data)

        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    else:
        # Not a GET or POST request
        return jsonify({'error': 'Method not allowed'}), 405
