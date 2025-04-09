# A wage calculator for the drivers of a haulage business.

Live site: https://jjcalc-d6c8df6b66e9.herokuapp.com/ <br>
Github: https://github.com/rhysjj111/PROJECT3_WAGE_CALCULATOR

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
- The app was designed mobile first, even though it is assumed it will be used more on the desktop. This is to ensure the content and navigation is kept simple. 

### Security
- I added back end validation to better protect my database from attacks. I would like to spend more time strengthening my validation as there will be sensitive information stored.
- I would like to add a login feature. Initially I didn't include this in my designs as it will only be used by one person. On reflection, the database will potentially be storing sensitive information and the extra layer of protection afforded by a login barrier is essential.
- I would also like to add some validation to the 'wages_calculator.html' form as I believe someone can easily cause harm there. I ran out of time.

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
- The finished product is fairly similar to the original plan. Key differences would be more robust validation in the finished product. The feedback to user was originally going to be predominantly Javascript but the finished product relies heavily on Flask's 'Flash'. 
- A lot of the styling also did not get implimented.



### Colour scheme
The colour pallet was found from an article on [canva.com](https://www.canva.com/learn/website-color-schemes/)
Fresh - #f7f5e6,
Vermillion - #333a56,
Sunshine - #52658f,
Clean - #e8e8e8.
- This was the original plan but I had run out of time.

### Form data validation
#### Add Driver form
First name - max characters 25.
Second name - max characters 25.
Base wage - Integer between 0 and 1000.
Bonus percentage - Integer between 0 and 50.

#### Day-end questions
Total earned - integer between 0 and 3000.



## Testing 
[Testing.md](./testing.md)


### Issues
- I had an issue getting the two large buttons, of 'data_entry.html', to resize but also keep an appealing page position when changing screen sizes. I overcame this by giving the buttons a height and with in vh and vw, so that the move with the screen size, but limiting them with max/min width/height. To keep them central to the page I used a container for the buttons and a similar technique to keep the container roughly 75% height of the screen, coupled with the Materializecss valign-wrapper. 

- To keep calculations free from error, currency values input by the user are converted from £ to pence before entered into the database, and converted back, when rendering templates and displaying back to the user. I had trouble getting the edit_driver and edit_day_end edit questions to display previous currency answers as a value. The first issue was the questions are constructed using a macro for both edit_driver and edit_day end. After researching the problem, I found you can pass a macro a function/another macro, I tried both of these methods to convert the currency, but it wouldn't work. After much googling and an inspect element, I found the issue to be formatting. The functions I was using were returning £x.xx whereas the html form would only accept x.xx as a value for the corresponding form.

- I had an issue when deploying my site to Heroku involving the versions of Flask I had installed. I had the latest version of Flask-SQLAlchemy in my requirements file and was following a tutorial to upload my app to Flask which used an older version. When trying to create the tables on my ElephantSQL database, `db.create_all` was throwing an error. This [Stack overflow](https://stackoverflow.com/questions/73961938/flask-sqlalchemy-db-create-all-raises-runtimeerror-working-outside-of-applicat) article informed me that I needed to push an app context before hand in the newer version.

- When adding validation to attempted form submissions, I came across a tutorial on [Medium](https://ed-a-nunes.medium.com/field-validation-for-backend-apis-with-python-flask-and-sqlalchemy-30e8cc0d260c) which showed how to use SQLAlchemy's built in validator decorator. The problem I was having, is when a form is submited and the 'post' route is followed, an error was being raised but my try, except block was not catching. A post on [stack overflow](https://stackoverflow.com/questions/18982610/difference-between-except-and-except-exception-as-e) where someone was having the same issue, highlighted the fact that the calling of the model (Driver model initially), was outside the try, except block.  
`Driver = first_name(...`    
`try: `  
&ensp;`db.session.add(driver)`  
became  
`try:`  
&ensp;`Driver = first_name(...`  
&ensp;`db.session.add(driver)`

- I had a hard time getting my add_driver route to prepopulate the form after an error with the previous answers. This required a lot of fiddling around so that I could use the 'driver' variable as both the previous answers, but also for the edit version of the question macro.

- Originally, I had functions at routes.py with a context processor so I could access them on the html pages. At routes.py most of the functions were used to alter values before they are committed to the database. I decided to primarily use the conversion functions at the validation stage, as they could be used to check for errors and actually convert values to the database. I found it difficult to find a way to migrate the functions from routes to models and I also wanted to use more functions in some macros (which take max 4). I came across [this article on Stack Overflow](https://stackoverflow.com/questions/6761825/importing-multiple-functions-from-a-python-module) which solved both of these issues. Moving all my functions to a module functions.py, I was able to access functions easily on each page and using 'import the functions as f', I could pass f to a macro and have access to all fucntions.

- I had trouble with validating based on two seperate fields of a day_end submission. I needed any new entries to have a unique driver and date so to avoid duplicate days for any one driver. I found [this helpful article](https://stackoverflow.com/questions/68366099/flask-sqlalchemy-validation-prevent-adding-to-relationship-based-on-other-field) and [SQLAlchemys documents](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_attach) which allowed me to use an event listener before flush and do some custom validation. The user can now edit existing entries with the same driver and date but cannot add new entries under same conditions.

#### JS
- Most of my Javascript was just initalizing Materialize components. There is some inline JS in base.html which I would like to consolidate but I ran out of time.

#### CSS
- I used Materialize CSS framework. Although I got the layout to a point I was happy, I would like to have spent more time on the colours and fonts.

#### Features
- Add driver and add day-end forms which feed to a database. Both tables are related.
- The information from these two tables can be queried and 'wages' calculated by the user.
- CRUD functionality means user can edit (in a modal) and delete all entries.


### Validators

- HTML
  - 

- CSS
  - 

- JS
 -

### Lighthouse


### Future features to include/update
In future, I'd like to:
- Include a login page for security
- Update the CSS
- Include javascript to provide the user with more feedback
- Expand the functionality and scope of the data input by user.
- I'd liked to have checked all the python, html, css and Javascript code in validators.


### Deployment
#### Creating tables in Gitpod
#### Creating db tables on Gitpod
- To create database run following commands:
```
from wages_calc import db, app
  with app.app_context():
    db.create_all()
```
#### Exporting data from Heroku to development environment
- Make sure that you have an empty database.
- Below is an example where the development database name is postgres.
- Run these commands from the CLI, ensure you do not have data you want to keep in a database called 'postgres'. You can substitute postgres for any name.
```
dropdb postgres
createdb postgres
PGPASSWORD=pe30b956095b85dbcc858ca8a88003bb1687004d3bfb5a855fa3780ae5904c238 pg_dump -h c3l5o0rb2a6o4l.cluster-czz5s0kz4scl.eu-west-1.rds.amazonaws.com -U u1gn7p79ue8ef3 dau2n8i4dqe30h | psql -h localhost -U user postgres
```
- Insert DATABASE PASSWORD into the command above. I have left all other details such as host name etc. of my current database.

##### Handling the development environment postgres connection issues
- When trying to connect to the postgres database and you encounter:
```
(.venv) haulageassist-4970329:~/haulage_assist{main}$ psql
psql: error: connection to server on socket "/tmp/postgres/.s.PGSQL.5432" failed: No such file or directory
Is the server running locally and accepting connections on that socket?
```
- Enter the following command to restart the database:
```
rm /tmp/postgres/.s.PGSQL.5432.lock
pg_ctl -D /home/user/haulage_assist/.idx/.data/postgres -o "-k /tmp/postgres" start
```
If you are using Project IDX, It may be that there is a stale postmaster.opts file in the .idx/.data/postgres directory. Remove this file and run the above command again.

#### Migrating database from Gitpod environment to Heroku
##### Login to Heroku via CLI
- Obtain Heroku api key from Heroku dashboard. Run:
- `heroku login -i`
- Follow instructions.
##### Upgrading Heroku database
- Run these commands in the Gitpod terminal:
- `flask db migrate -m "Description."`
- `flask db upgrade`
- Check migrations are ok within development environment.
- Push changes to GitHub. Run following command:
- `heroku run -a jjcalc flask db upgrade`

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
##### Heroku
- Make sure your repository contains your 'requirements.txt' file, which contains relevant packages, and a 'Procfile' which tells Heroku how to start your app.
- Create a Heroku account & login.
- Click 'New' followed by 'Create new app'.
- Choose a name for your app and select a region close to you. Click 'Create app'.
- Go to 'settings' and click 'Reveal Config Vars'.
- Add Key value pairs as below, using your ElephantSQL URL that you copied earlier for the DATABASE_URL.

|KEY         |VALUE                 |
|------------|----------------------|
|DATABASE_URL|(url from ElephantSQL)|
|IP          |0.0.0.0               |
|PORT        |5000                  |
|SECRET_KEY  |(your secret key)     |
|DEBUG       |True                  |

- Debug is set to True if you want to check for any bugs/errors. You can set to False straight away if you do not want debug mode, or once deployed and you are happy.
- Locate 'Deploy' (next to settings). Click 'Connect to GitHub' (look for the logo).
- Connect your repository.
- Locate 'Deploy Branch' of Manual Deploy and click.
- Look for conformation the app is deployed.
- If not, enable automatic deploys and commit and push the repository to GitHub.
- Next, add your tables to your database. Click 'More' and 'Run console'. It will say `Heroku run` - type 'python3' and click 'run'.
- Create all tables, the commands you use will depend on the version of Flask you have in requirements.txt. I used `from wages_calculator import app, db` then `app.app_context().push()` then `db.create_all()`. Close the console.
- Finally go back to the dashboard and click 'Open app'.
- Use the Heroku documentation if there are any issues.



### Credits
- The colour pallet was found on: https://www.canva.com/learn/website-color-schemes/
- A helpful article on [Stack overflow](https://stackoverflow.com/questions/19216334/python-give-start-and-end-of-week-data-from-a-given-date) gave me the solution to finding the start and end date of the week from a given date.
- [SQLAlchemy docs](https://docs.sqlalchemy.org/en/20) were used a lot to determine how to query the database via ORM.
- This [Stack overflow](https://www.tutorialspoint.com/how-to-check-an-element-with-specific-id-exist-using-javascript) explained how to check an element for a particular Id, which I had needed for the Javascript to only show Mondays on the wages calculator datepicker.
- [Stack overflow](https://stackoverflow.com/questions/51205600/datepicker-materializecss-disabled-days-function) This article explained how to use the disable days funtion of the Materialize datepicker.
- [Stack overflow](https://stackoverflow.com/questions/21991820/style-active-navigation-element-with-a-flask-jinja2-macro) and [TTL25's Jinja2 tutorial](https://ttl255.com/jinja2-tutorial-part-5-macros/) were both used when constructing the nav_link macro, used to determine which navigation link should be active. The Stack overflow thread gave me the basic structure of the macro, and the tutorial allowed me to understand Jinja's varargs keyword so that I could expand the macro to also take into account sub-menu pages.
- [Stack overflow](https://stackoverflow.com/questions/73961938/flask-sqlalchemy-db-create-all-raises-runtimeerror-working-outside-of-applicat) - This article helped me update my ElephantSQL database with my tables, running the newest version of Flask-SQLAlchemy.
- [Medium](https://ed-a-nunes.medium.com/field-validation-for-backend-apis-with-python-flask-and-sqlalchemy-30e8cc0d260c) and [stack overflow](https://stackoverflow.com/questions/18982610/difference-between-except-and-except-exception-as-e) helped with form validation at the back end.
- This article on [Stack overflow](https://stackoverflow.com/questions/29017379/how-to-make-fadeout-effect-with-pure-javascript) helped me with transitioning out flash messages using css and Javascript.

