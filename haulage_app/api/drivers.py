from flask import jsonify, request
from haulage_app.models import Driver
from . import api_bp

@api_bp.route('/drivers', methods=['GET'])
def get_drivers():
    """
    Get a list of drivers.

    Query parameters:
    - name: Filter by driver name (partial match).
    - sort_by: Sort by a specific field ('id', 'first_name', 'last_name', 'timestamp').
    - sort_order: Sort order ('asc' or 'desc').

    Returns:
    - JSON response with a list of drivers.
    """

    # Get query parameters
    name_filter = request.args.get('name')
    sort_by = request.args.get('sort_by', 'id')  # Default sort by 'id'
    sort_order = request.args.get('sort_order', 'asc')  # Default sort order 'asc'

    # Start building the query
    query = Driver.query

    # Apply name filter
    if name_filter:
        query = query.filter(
            Driver.first_name.ilike(f'%{name_filter}%') | 
            Driver.last_name.ilike(f'%{name_filter}%')
        )

    # Apply sorting
    if sort_by in ['id', 'first_name', 'last_name', 'timestamp']:
        sort_column = getattr(Driver, sort_by)
        if sort_order == 'desc':
            sort_column = sort_column.desc()
        query = query.order_by(sort_column)

    # Execute the query and format the results
    drivers = query.all()
    driver_list = [{'id': driver.id, 
                    'name': driver.full_name,
                    'truck_id': driver.truck_id} for driver in drivers]

    return jsonify(driver_list)