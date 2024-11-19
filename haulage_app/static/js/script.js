document.addEventListener('DOMContentLoaded', function () {
    // collapsible initialization
    const collapsibles = document.querySelectorAll('.collapsible');
    M.Collapsible.init(collapsibles);

    // datepicker initialization
    let datepicker = document.querySelectorAll('.datepicker');
    M.Datepicker.init(datepicker, {
        format: "dd/mm/yyyy",
        i18n: {done: "Select"},
        // disable all days apart from Monday for 'wages' page datepicker
        disableDayFn: function(date){
            if(document.querySelector('#wages_date') != null){
                if(date.getDay() == 1){
                return false;
                } else {
                return true;
                };
            }   
        }
    })


    // sidenav initialization
    let sidenavigation = document.querySelectorAll('.sidenav');
    M.Sidenav.init(sidenavigation);


    // modal initialisation
    let modal = document.querySelectorAll('.modal');
    M.Modal.init(modal, {
        endingTop: '10%',
        preventScrolling: false
    });
    // edit-modal re-open when invalid form submission
    let modalOpen = document.querySelector('.open-modal')
    if (modalOpen){
        modalOpen = modalOpen.textContent;
        modalOpen = document.querySelector(`#${modalOpen}`);
        M.Modal.init(modalOpen).open();
    };


    // select initialization
    let selects = document.querySelectorAll('select');
    M.FormSelect.init(selects);


    // remove sub menu tabs for 'entry' and 'history' of entry pages on screen sizes desktop and over
    function removeTabs() {
        const subTabs = document.querySelector('#sub-menu-tabs')
        if (subTabs) {
            const tabs = M.Tabs.init(subTabs, swipeable=true);
            if(window.innerWidth > 992){
                tabs.destroy();
            } else {
                tabs;
            }
        }
    }
    window.onresize = removeTabs;
    removeTabs();

    // Initialize Materialize dropdown
    let notification_dropdown = document.querySelectorAll('.dropdown-trigger');
     M.Dropdown.init(notification_dropdown, {
        alignment: 'left',
        coverTrigger: false,
        constrainWidth: false
    });
    
    //flash feedback timeout and remove container after a time interval
    // const messageContainer = document.querySelector(".scc-msg");
    // if (messageContainer){
    //     setTimeout(changePropertiesToZero, 1000, 'opacity', 'height', 'margin', 'padding', 'border');
    // }
    // //pass message container style property names
    // function changePropertiesToZero(...properties){
    //     properties.forEach((value) => messageContainer.style[value] = '0');
    // }

    const closeMessages = document.querySelectorAll('.close-messages');
    closeMessages.forEach(button => {
    button.addEventListener('click', () => {
        button.closest('.messages-container').style.display = 'none';
        });
    });

    // A funtion to toggle the visibility of working questions based on the status selection
    const statusSelects = document.querySelectorAll('select[name="status"]');
    statusSelects.forEach(statusSelect => {
        // Get working questions only within this form
        const form = statusSelect.closest('form');
        const workingQuestions = form.querySelectorAll('.working_question');
        
        // Initial check on page load
        toggleWorkingQuestions();
        
        // Add listener for status changes
        statusSelect.addEventListener('change', toggleWorkingQuestions);
        
        function toggleWorkingQuestions() {
            const isWorking = statusSelect.value === 'working';
            workingQuestions.forEach(question => {
                question.style.display = isWorking ? 'block' : 'none';
            });
        }
    });


})


const splitInput = document.querySelector('#split');
const lever = document.querySelector('.lever');
const nwdInput = document.querySelector('#date_nwd')
const nwdContainer = document.querySelector('.nwd-container');
lever.addEventListener('click', () => {
    if (splitInput.checked) {
        nwdContainer.classList.add('hide');
        nwdInput.removeAttribute('required','');
    } else {
        nwdContainer.classList.remove('hide');
        nwdInput.setAttribute('required','');
    }
})


