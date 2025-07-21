from haulage_app import db, app
from haulage_app.models import Day, Fuel, Payslip
from haulage_app.verification.checks.verification_functions import (
    check_missing_day_has_been_rectified,
    check_missing_fuel_has_been_rectified,
    check_missing_payslip_has_been_rectified,
    check_mileage_has_been_rectified
)

with app.app_context():
    print("Starting rectification checks for all entries...\n")
    
    # Check Day entries
    print("=" * 50)
    print("CHECKING DAY ENTRIES")
    print("=" * 50)
    day_entries = Day.query.all()
    day_entry_ids = [day.id for day in day_entries]
    
    print(f"Found {len(day_entry_ids)} Day entries to check")
    
    for i, day_entry_id in enumerate(day_entry_ids, 1):
        print(f"Checking Day entry {i}/{len(day_entry_ids)} (ID: {day_entry_id})")
        check_missing_day_has_been_rectified(day_entry_id)
    
    # Check Fuel entries
    print("\n" + "=" * 50)
    print("CHECKING FUEL ENTRIES")
    print("=" * 50)
    fuel_entries = Fuel.query.all()
    fuel_entry_ids = [fuel.id for fuel in fuel_entries]
    
    print(f"Found {len(fuel_entry_ids)} Fuel entries to check")
    
    for i, fuel_entry_id in enumerate(fuel_entry_ids, 1):
        print(f"Checking Fuel entry {i}/{len(fuel_entry_ids)} (ID: {fuel_entry_id})")
        check_missing_fuel_has_been_rectified(fuel_entry_id)
    
    # Check Payslip entries
    print("\n" + "=" * 50)
    print("CHECKING PAYSLIP ENTRIES")
    print("=" * 50)
    payslip_entries = Payslip.query.all()
    payslip_entry_ids = [payslip.id for payslip in payslip_entries]
    
    print(f"Found {len(payslip_entry_ids)} Payslip entries to check")
    
    for i, payslip_entry_id in enumerate(payslip_entry_ids, 1):
        print(f"Checking Payslip entry {i}/{len(payslip_entry_ids)} (ID: {payslip_entry_id})")
        check_missing_payslip_has_been_rectified(payslip_entry_id)
    
    # Check Mileage (using Day entries since mileage is part of Day model)
    print("\n" + "=" * 50)
    print("CHECKING MILEAGE ANOMALIES")
    print("=" * 50)
    print(f"Found {len(day_entry_ids)} Day entries to check for mileage anomalies")
    
    for i, day_entry_id in enumerate(day_entry_ids, 1):
        print(f"Checking Mileage for Day entry {i}/{len(day_entry_ids)} (ID: {day_entry_id})")
        check_mileage_has_been_rectified(day_entry_id)
    
    print("\n" + "=" * 50)
    print("FINISHED CHECKING ALL ENTRIES")
    print("=" * 50)