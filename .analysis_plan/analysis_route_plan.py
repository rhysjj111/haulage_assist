# Below is the desired json structure to be achieved within an analysis route.

[
  {
    # week details
    "week_start_date": "2025-05-26",
    "week_end_date": "2025-06-01",
    "year": 2025,
    "week_number": 22,
    "status": "Partial/Estimated/Complete",

    # weekly totals
    "period_total_earned": 640.00,
    "period_total_estimated_fuel_sum": 85.00,
    "period_total_actual_fuel_sum": 25.00,
    "period_total_calculated_wage_sum": 192.00,
    "period_total_estimated_wage_sum": 192.00,
    "period_total_actual_wage_sum": 60.00,
    "period_total_running_costs": 262.50,
    "period_total_costs_best_available": 262.50,
    "period_net_profit_best_available": 377.50,
    "period_fuel_status": "Estimated/Actual",
    "period_wage_status": "Estimated/Actual",

    # weekly breakdown by driver
    "drivers": [
      {
        "driver_id": 1,
        "driver_name": "Alice Wonderland",
        "truck_id": 1,
        "weekly_earned": 430.00,
        "weekly_estimated_fuel_sum": 50.00,
        "weekly_actual_fuel_sum": 25.00,
        "weekly_calculated_wage_sum": 129.00,
        "weekly_estimated_cost_to_employer": 129.00,
        "weekly_actual_cost_to_employer": 60.00,
        "weekly_running_costs": 159.00,
        "weekly_total_costs_best_available": 159.00,
        "weekly_net_profit_best_available": 271.00,
        "weekly_fuel_status": "Estimated/Actual",
        "weekly_wage_status": "Estimated/Actual",
        "days_worked": 5,
        "daily_breakdown": [
          {
            "day_id": 1,
            "date": "2025-05-26",
            "status": "working/absent/holiday",
            "day_start_mileage": 70.0,
            "day_end_mileage": 100.0,
            "day_calculated_mileage": 30.0,
            "daily_earned": 230.00,
            "overnight": True/False,
            "fuel_flag": True/False,
            "daily_bonus": 0.00,
            "daily_estimated_fuel_sum": 25.00,
            "jobs": [
              {
                "job_id": 1,
                "earned": 150.00,
                "collection": "Derby",
                "delivery": "Nottingham",
                "split": True/False,
              },
            ],
            "fuel_entries_details": [
              {
                "fuel_id": 1,
                "fuel_cost": 25.00,
                "fuel_litres": 25.00,
              }
            ],
          },
        ]
      }
    ]
  }
]