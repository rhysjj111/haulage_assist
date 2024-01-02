# Testing
This document is an extention of README.md and contains the tests carried out on wages_calculator app.

## Form validation

### Add driver
These tests are carried out when a user attempts to add a driver. All front end validation was removed (ie. required attribute at html of question) All other questions to the question being tested will be given a standard acceptable answer.

#### New entries

**Question** | **Answer given** | **Expected outcome** | **Result** | **Pass/Fail**
:-----:|:-----:|:-----:|:-----:|:-----:
Start date | 30 Decemeber 2016 | Validation warning message. Form not submitted. | 'Please enter date in format dd/mm/yyyy'. Form not submitted.| Pass
Start date | 30/12/2016 | Success message. Form submitted and data stored in database | 'Success'. Data in database.| Pass
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
Base wage | 1250 | Success message. Form submitted. Data stored in database | 'Success'. Data in database | Pass
Bonus percentage | 51 | Validation warning message. Form not submitted.| 'Please enter a bonus percentage value between 15 and 50'. Form not submitted | Pass
Bonus percentage | 14 | Validation warning message. Form not submitted.| 'Please enter a bonus percentage value between 15 and 50'. Form not submitted | Pass
Bonus percentage | abc | Validation warning message. Form not submitted.| 'Please enter a bonus percentage value between 15 and 50'. Form not submitted | Pass
Bonus percentage | 25 | Success message. Form submitted. Data stored in database | 'Success'. Data in database | Pass

#### Edit entries
Each of the above parameters were tested when editing an entry. A key difference is the user edits an entry in a modal and this must be re-opened with the pre-populated form, and warning message. If no validation is required, the main driver entry page is loaded with the success message. Another difference comes because, if the user does not change the name, the validation checks the database and finds the same name and throws an error. A check at the edit route skips this validation if the name is the same as it was before the user submits the edit form.

#### Delete entries
A warning modal pops up prompting the user to confirm deleting an entry. On confirmation, the selected driver gets deleted each time.

### Add day-end
These tests are carried out when a user attempts to add a day-end entry. All front end validation was removed (ie. required attribute at html of question) All other questions to the question being tested will be given a standard acceptable answer.

**Question** | **Answer given** | **Expected outcome** | **Result** | **Pass/Fail**
:-----:|:-----:|:-----:|:-----:|:-----:
Select Driver | (entered a driver not on database) | Validation warning message. Form not submitted. | 'Selection not available in database. Please select a driver.'. Form not submitted.| Pass
Select Driver | (empty string) | Validation warning message. Form not submitted. | 'Selection not available in database. Please select a driver.'. Form not submitted.| Pass
Select Driver | (entered a valid driver) | Success message. Form submitted. Data stored in database | 'Success'. Data stored in database.| Pass
Date | 30 Decemeber 2016 | Validation warning message. Form not submitted. | 'Please enter date in format dd/mm/yyyy'. Form not submitted.| Pass
Date | (empty string) | Validation warning message. Form not submitted. | 'Please enter date in format dd/mm/yyyy'. Form not submitted.| Pass
Date | 22/06/2022 | Success message. Form submitted. Data stored in database | 'Success'. Data stored in database.| Pass
Earned | 0.2 | Validation warning message. Form not submitted.| 'Please enter a value earned between 1 and 2000'. Form not submitted | Pass
Earned | 2001 | Validation warning message. Form not submitted.| 'Please enter a value earned between 1 and 2000'. Form not submitted | Pass
Earned | abc | Validation warning message. Form not submitted.| 'Please enter a value earned between 1 and 2000'. Form not submitted | Pass
Earned | 350 | Success message. Form submitted. Data stored in database | 'Success'. Data in database | Pass
Overnight | (entered a string) | Validation warning message. Form not submitted. | 'Please use the selector to indicate whether overnight is present'. Form not submitted.| Pass
Earned | abc | Validation warning message. Form not submitted. | 'Please use the selector to indicate whether overnight is present'. Form not submitted.| Pass
Earned | abc | Validation warning message. Form not submitted. | 'Please use the selector to indicate whether overnight is present'. Form not submitted.| Pass
Earned | (use selector) | Success message. Form submitted. Data stored in database | 'Success'. Data stored in database.| Pass

#### Edit entries
Each of the above parameters were tested when editing an entry. A key difference is the user edits an entry in a modal and this must be re-opened with the pre-populated form, and warning message. If no validation is required, the main driver entry page is loaded with the success message. Another difference comes because, if the user does not change the name, the validation checks the database and finds the same name and throws an error. A check at the edit route skips this validation if the name is the same as it was before the user submits the edit form.

#### Delete entries
A warning modal pops up prompting the user to confirm deleting an entry. On confirmation, the selected driver gets deleted each time.






