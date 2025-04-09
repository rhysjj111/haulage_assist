from flask_wtf import FlaskForm
from wtforms import (
    StringField, 
    IntegerField, 
    DateField, 
    SelectField, 
    SubmitField, 
    DecimalField, 
    HiddenField,
    BooleanField,
    ValidationError,
    FieldList,
    FormField,

)
from wtforms.validators import (
    DataRequired, 
    NumberRange,
    Length, 
    Optional,

)
from wtforms_sqlalchemy.orm import model_form
from wtforms.widgets import TextInput, Select, CheckboxInput, HiddenInput
from haulage_app.models import Driver, Truck, Day
from haulage_app.functions import float_to_db, display_float


class DatePickerWidget(TextInput):
    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', "date")
        kwargs.setdefault('type', 'text')  # Change type to text for datepicker
        kwargs.setdefault('class', 'datepicker')  # Add the datepicker class
        if field.data:
            kwargs.setdefault('value', field.data.strftime('%Y-%m-%d'))
        return super().__call__(field, **kwargs)

# # Create a custom widget for status selection
class StatusSelectWidget(Select):
    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', "status")
        kwargs.setdefault('class', 'validate')  # Materialize CSS class for styled select
        return super().__call__(field, **kwargs)

# Create a custom field for status
class StatusField(SelectField):
    widget = StatusSelectWidget()
    
    def __init__(self, label=None, validators=None, **kwargs):
        super(StatusField, self).__init__(
            label=label,
            validators=validators,
            choices=[
                ('working', 'Working'),
                ('holiday', 'Holiday'),
                ('absent', 'Absent')
            ],
            **kwargs
        )

# Create a custom widget for truck selection
class TruckSelectWidget(Select):
    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', "truck")
        kwargs.setdefault('class', 'validate')  # Materialize CSS class for styled select
        return super().__call__(field, **kwargs)

# Create a custom field for truck selection
class TruckField(SelectField):
    widget = TruckSelectWidget()

    def __init__(self, label=None, validators=None, **kwargs):
        super(TruckField, self).__init__(
            label=label,
            validators=validators,
            coerce=int,  # Convert the value to integer (truck_id)
            **kwargs
        )
        # Dynamically load truck choices when the form is instantiated
        self.choices = [(truck.id, truck.registration) for truck in Truck.query.all()]
    
# class TruckSelectWidget(Select):
#     def __call__(self, field, **kwargs):
#         kwargs.setdefault('id', "truck")
#         kwargs.setdefault('class', 'validate')  # Materialize CSS class for styled select
#         return super().__call__(field, **kwargs)
    
#     def render_option(self, selected_choices, value, label):
#         # This method is called for each option in the select
#         # We override it to add the 'selected' attribute to the correct option
#         if value is None:
#             value = ''
#         selected = (value in selected_choices)
        
#         # Convert to string for comparison
#         if isinstance(value, int) or isinstance(value, float):
#             value = str(value)
            
#         options = {'value': value}
#         if selected:
#             options['selected'] = True
#             # Add a 'selected' class for Materialize to recognize
#             options['class'] = 'selected'
        
#         return f'<option {" ".join([f"{k}=\"{v}\"" for k, v in options.items()])}>{label}</option>'


# Custom field for mileage that handles the multiplication/division by 100
class FloatField(IntegerField):
    def process_formdata(self, valuelist):
        if valuelist and valuelist[0]:
            try:
                # When form is submitted, multiply by 100 before storing
                self.data = float_to_db(valuelist[0])
            except ValueError:
                self.data = None
                raise ValueError('Not a valid integer value')
        else:
            self.data = 0
    
    def _value(self):
        # When displaying the form, divide by 100
        if self.data is not None:
            return display_float(self.data)
        return 0

class DayForm(FlaskForm):
    id = HiddenField('ID')
    date = DateField('Date', widget=DatePickerWidget(), validators=[Optional()])
    start_mileage = FloatField('Start Mileage', validators=[Optional()])
    end_mileage = FloatField('End Mileage', validators=[Optional()])
    truck = TruckField('Truck', validators=[Optional()])
    overnight = BooleanField('Overnight')
    fuel = BooleanField('Fuel')
    status = StatusField('Status', validators=[DataRequired()])
