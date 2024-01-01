# Testing
This document is an extention of README.md and contains the tests carried out on wages_calculator app.

## Form validation

### Add driver
These tests are carried out when a user attempts to add a driver. All front end validation was removed (ie. required attribute at html of question) All other questions to the question being tested will be given a standard acceptable answer.

####

**Question** | **Answer given** | **Expected outcome** | **Result** | **Pass/Fail**
:-----:|:-----:|:-----:|:-----:|:-----:
Date | 30 Decemeber 2016 | Validation warning message. Form not submitted. | 'Please enter date in format dd/mm/yyyy'. Form not submitted.| Pass
Date | 30/12/2016 | Success message. Form submitted and data stored in database | 'Success'. Data in database.| Pass
First name/Second name|(Nothing entered)|Validation warning message. Form not submitted.| "Please enter first and second name". Form not submitted| Pass
First name/Second name | 5/Phillips | Validation warning message. Form not submitted. | "Please do not include numbers in name(s)". Form not submitted | Pass
First name/Second name | Rhys J/Johnston | Validation warning message. Form not submitted. | 'Please do not inlude spaces or special characters in name(s), for double barrel names use: "-"'. Form not submitted | Pass
First name/Second name | asdfasdfasdfasdfasdfSADFasdfasdf/Stevens | Validation warning message. Form not submitted. | 'Please enter name(s) between 1 and 25 characters'. Form not submitted | Pass
First name/Second name | (Combination of first and second name that is already added) | Validation warning message. Form not submitted. | 'Driver name already exists. Edit current entry or choose another name'. Form not submitted | Pass
First name/Second name | (Name including special characters) | Validation warning message. Form not submitted. | 'Please do not inlude spaces or special characters in name(s), for double barrel names use: "-"'. Form not submitted | Pass
First name/Second name | (A combination of strings that is unique) | Success message. Form submitted. Data stored in database | 'Success'. Data in database | Pass
Base wage | 2001 | Validation warning message. Form not submitted.| 'Please enter a base wage between 400 and 2000'. Form not submitted | Pass
Base wage | 300 | Validation warning message. Form not submitted.| 'Please enter a base wage between 400 and 2000'. Form not submitted | Pass
Base wage | abc | Validation warning message. Form not submitted.| 'Please enter a base wage between 400 and 2000'. Form not submitted | Pass
Base wage | 425.001 | Validation warning message. Form not submitted.| 'Please enter a base wage in £; ie "450.50" or "450"'. Form not submitted | Pass
Base wage | 1250 | Success message. Form submitted. Data stored in database | 'Success'. Data in database | Pass
Bonus percentage | 51 | Validation warning message. Form not submitted.| 'Please enter a bonus percentage between 15 and 50'. Form not submitted | Pass
Bonus percentage | 14 | Validation warning message. Form not submitted.| 'Please enter a bonus percentage between 15 and 50'. Form not submitted | Pass
Bonus percentage | abc | Validation warning message. Form not submitted.| 'Please enter a bonus percentage between 15 and 50'. Form not submitted | Pass
Bonus percentage | 400.002 | Validation warning message. Form not submitted.| 'Please enter a bonus percentage in %, to 2 decimal places; ie "35.25" or "27"'. Form not submitted | Pass
Bonus percentage | 25 | Success message. Form submitted. Data stored in database | 'Success'. Data in database | Pass





