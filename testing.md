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
First name/Second name | 5/Phillips | Validation warning message. Form not submitted. | "Please do not include numbers in names". Form not submitted | Pass
First name/Second name | Rhys J/Johnston | Validation warning message. Form not submitted. | 'Please do not inlude spaces in "First name", for double barrel names use: "-"'. Form not submitted | Pass
First name/Second name | asdfasdfasdfasdfasdfSADFasdfasdf/Stevens | Validation warning message. Form not submitted. | 'Please enter name(s) between 1 and 25 characters'. Form not submitted | Pass
First name/Second name | (Combination of first and second name that is already added) | Validation warning message. Form not submitted. | 'Driver name already exists. Edit current entry or choose another name'. Form not submitted | Pass
First name/Second name | (A combination of strings that is unique) | Success message. Form submitted. Data stored in database | 'Success'. Form not submitted | Pass
First name/Second name | (A combination of strings that is unique) | Success message. Form submitted. Data stored in database | 'Success'. Form not submitted | Pass



