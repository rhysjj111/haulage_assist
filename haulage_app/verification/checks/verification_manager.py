from haulage_app.verification.checks.verification_functions import(
    get_all_missing_payslip_weeks,
    process_missing_payslips,
    check_all_missing_fuel_data,
    process_missing_fuel_data,
    check_all_missing_day_entries,
    process_missing_day_entries,
)

def payslip_check():
    missing_payslip = get_all_missing_payslip_weeks()
    if missing_payslip != {}:
        process_missing_payslips(missing_payslip)
    else:
        print('no missing payslips')

def fuel_check():
    missing_fuel = check_all_missing_fuel_data()
    if missing_fuel != []:
        process_missing_fuel_data(missing_fuel)
    else:
        print('no missing fuel')

def day_check():
    missing_days = check_all_missing_day_entries()
    if missing_days != []:
        process_missing_day_entries(missing_days)
    else:
        print('no missing days')
