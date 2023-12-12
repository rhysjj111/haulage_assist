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


### Credits
- The colour pallet was found on: https://www.canva.com/learn/website-color-schemes/
- A helpful article on [Stack overflow](https://stackoverflow.com/questions/19216334/python-give-start-and-end-of-week-data-from-a-given-date) gave me the solution to finding the start and end date of the week from a given date.
- [SQLAlchemy docs](https://docs.sqlalchemy.org/en/20) were used a lot to determine how to query the database via ORM.

