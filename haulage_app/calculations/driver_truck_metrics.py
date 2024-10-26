def calculate_driver_metrics(driver, Day, Job, start_date, end_date):
    weekly_total_earned = 0
    weekly_total_overnight = 0
    weekly_total_bonus_wage = 0
    weekly_total_wage = 0
    weekly_bonus = 0
    
    day_entries = Day.query.filter(
        Day.driver_id == driver.id,
        Day.date >= start_date,
        Day.date <= end_date
        ).order_by(Day.date).all()
    job_entries = Job.query.join(Day).filter(
        Day.driver_id == driver.id,
        Day.date >= start_date,
        Day.date <= end_date
        ).order_by(Day.date, Job.id).all()

    for day in day_entries:
        day.daily_bonus = day.calculate_daily_bonus(driver)
        weekly_total_bonus_wage += day.daily_bonus
        weekly_total_earned += day.calculate_total_earned()
        if day.overnight == True:
            weekly_total_overnight += 3000
            
    if weekly_total_earned > driver.weekly_bonus_threshold:
        weekly_bonus = (weekly_total_earned - driver.weekly_bonus_threshold) * driver.weekly_bonus_percentage
        weekly_total_bonus_wage += weekly_bonus
        
    weekly_extras = weekly_total_bonus_wage - (15000 - weekly_total_overnight)
    weekly_total_wage = weekly_extras + driver.basic_wage

    return {
        'driver': driver,
        'day_entries': day_entries,
        'weekly_total_earned': weekly_total_earned,
        'weekly_total_overnight': weekly_total_overnight,
        'weekly_total_bonus_wage': weekly_total_bonus_wage,
        'weekly_total_wage': weekly_total_wage,
        'weekly_bonus': weekly_bonus,
        'weekly_extras': weekly_extras,
        'start_date': start_date,
        'end_date': end_date,
        'job_entries': job_entries
    }