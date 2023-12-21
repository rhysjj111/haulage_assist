# A wage calculator for the drivers of a haulage business.

## UX

### Overview
This project is for an imaginary haulage business that pays it's employees with a bonues scheme based on what they earn during the week. The user will be the fleet manager and will be able to add drivers (and their bonus plans), as well as how much they earn each day. The calculator will then give their wages total for any given week that has entries. The fleet manager will be able to add, remove and edit each of these variables.

### Site owners goals
To provide a service that the customer will be happy to pay a subsctiption fee for.

### External users goals
* Save time for employees by automating a labour intesive task. 
* Save time for employees searching for wages details.

### Developer goals
- To build a functional app that can be replicated for other business situations.

### Proposed features
- A database that takes entries for driver details, and their daily earnings. This information should be called upon and manipulated to give the wages for any driver, of any given week.
- A history of all entries that can be edited/deleted.
- Notify the user of a successful entry with a flashing tab.
- A tab for the wages calculator.

The features listed are achievable in terms of timescales and technology available.

### User stories
- As a user of this app, I will want to be able to intuitively navigate it to easily add, remove and edit data. 
- I should be able to easily find the wages of any driver which I normally caluclate manually.

## Design

### Design choices
- I've chosen a simple design which can be expanded on with more data inputs and features in the future.
- A professional, clean color scheme will be used, as this app will be used day to day by the fleet manager.
- The app will have two main menu tabs at the bottom of the page so the user can flick with ease between data input and the wages calculator. Within data input, the user can choose between 'driver' and 'end day' sections. 
- The app was designed mobile first, even though it is suspected it will be used more on the desktop. This is to ensure the content and navigation is kept simple. 

### Security
- 

### Wireframes
Desktop wireframes:
![Desktop wireframes](/wages_calculator/static/images/wireframes/project3_desktop_wf.png)

Tablet wireframes:
![Tablet wireframes](/wages_calculator/static/images/wireframes/project3_tablet_wf.png)

Mobile wireframes:
![Mobile wireframes](/wages_calculator/static/images/wireframes/project3_mobile_wf.png)



### Plan
![Database structure and templates plan](/wages_calculator/static/images/wireframes/database_plan.png)

- This is the structure of the database and jinja templates that will be used.


### End design similarity/difference
-JS


- HTML & CSS



### Colour scheme
The colour pallet was found from an article on [canva.com](https://www.canva.com/learn/website-color-schemes/)
Fresh - #f7f5e6,
Vermillion - #333a56,
Sunshine - #52658f,
Clean - #e8e8e8.

### Form data validation
#### Add Driver form
First name - max characters 25.
Second name - max characters 25.
Base wage - Integer between 0 and 1000.
Bonus percentage - Integer between 0 and 50.

#### Day-end questions
Total earned - integer between 0 and 3000.



## Testing 

### Functionality testing


### Issues
- I had an issue getting the two large buttons, of 'data_entry.html', to resize but also keep an appealing page position when changing screen sizes. I overcame this by giving the buttons a height and with in vh and vw, so that the move with the screen size, but limiting them with max/min width/height. To keep them central to the page I used a container for the buttons and a similar technique to keep the container roughly 75% height of the screen, coupled with the Materializecss valign-wrapper. 

- To keep calculations free from error, currency values input by the user are converted from £ to pence before entered into the database, and converted back, when rendering templates and displaying back to the user. I had trouble getting the edit_driver and edit_day_end edit questions to display previous currency answers as a value. The first issue was the questions are constructed using a macro for both edit_driver and edit_day end. After researching the problem, I found you can pass a macro a function/another macro, I tried both of these methods to convert the currency, but it wouldn't work. After much googling and an inspect element, I found the issue to be formatting. The functions I was using were returning £x.xx whereas the html form would only accept x.xx as a value for the corresponding form.

#### JS


#### CSS
- 

#### Features



### Validators

- HTML
  - 

- CSS
  - 

- JS
 -

### Lighthouse


### Future features to include/update
- NOTE: CONVERTING MONEY INTO INTEGER FOR STORAGE IN DATABASE AND CALCULATIONS(BETTER THAN FLOATING POINT)


### Deployment
#### Deploy locally
##### Fork the repository (creating a copy)
- Create a Github account & login.
- Locate the GitHub Repository [here](https://github.com/rhysjj111/PROJECT3_WAGE_CALCULATOR)
- Locate the 'Fork' button and click.
- Find the copied repository in your GitHub repository list.

##### Clone the repository
- Create a Github account & login.
- Locate the GitHub Repository [here](https://github.com/rhysjj111/PROJECT3_WAGE_CALCULATOR)
- Locate the 'code' button and click.
- Copy the URL (be sure to click whether you prefer HTTPS, SSH or GitHub CLI).
- Open Git Bash or Terminal or Command Prompt/Powershell.
- Enter 'git clone' followed by copied url: `git clone https://github.com/rhysjj111/PROJECT3_WAGE_CALCULATOR.git`
- Hit enter and you should have your local clone in the directory you have specified.

#### Deploy with Heroku using ElephantSQL as the database
##### Elephant SQL
- Create an Elephant SQL account & login.
- Fill in the 'Create new team' form.
- Click 'Create instance'
- Come up with a name for your instance and any tags necessary. Click 'Select Region'.
- Select a location/data center near you. Click 'Review'.
- Check details are correct and click 'Create instance'.
- In your dashboard, go into the instance and copy the URL.
- 
- 
- Create a Heroku account & login.
- Cr



### Credits
- The colour pallet was found on: https://www.canva.com/learn/website-color-schemes/
- A helpful article on [Stack overflow](https://stackoverflow.com/questions/19216334/python-give-start-and-end-of-week-data-from-a-given-date) gave me the solution to finding the start and end date of the week from a given date.
- [SQLAlchemy docs](https://docs.sqlalchemy.org/en/20) were used a lot to determine how to query the database via ORM.
- This [Stack overflow](https://www.tutorialspoint.com/how-to-check-an-element-with-specific-id-exist-using-javascript) explained how to check an element for a particular Id, which I had needed for the Javascript to only show Mondays on the wages calculator datepicker.
- [Stack overflow](https://stackoverflow.com/questions/51205600/datepicker-materializecss-disabled-days-function) This article explained how to use the disable days funtion of the Materialize datepicker.
- [Stack overflow](https://stackoverflow.com/questions/21991820/style-active-navigation-element-with-a-flask-jinja2-macro) and [TTL25's Jinja2 tutorial](https://ttl255.com/jinja2-tutorial-part-5-macros/) were both used when constructing the nav_link macro, used to determine which navigation link should be active. The Stack overflow thread gave me the basic structure of the macro, and the tutorial allowed me to understand Jinja's varargs keyword so that I could expand the macro to also take into account sub-menu pages.

