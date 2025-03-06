document.addEventListener('DOMContentLoaded', function () {
    // collapsible initialization
    const collapsibles = document.querySelectorAll('.collapsible');
    M.Collapsible.init(collapsibles);

    const collapsibleExpandable = document.querySelector('.collapsible.expandable');
    M.Collapsible.init(collapsibleExpandable, {
        accordion: false
    });

    const searchInput = document.getElementById('search-entries');
    const collapsibleItems = document.querySelectorAll('.collapsible li');

    if (searchInput) {
        searchInput.addEventListener('input', function (event) {
            const inputString = event.target.value.toLowerCase();
            const commaSplitTerms = inputString.split('+'); // Split by '+' first

            let finalFilteredItems = new Set();

            commaSplitTerms.forEach((commaSplitTerm, commaIndex) => {
                const searchTerms = commaSplitTerm.split(',').map(term => term.trim()).filter(term => term !== ""); // Split by comma, trim spaces, and remove empty strings
                let filteredItems = new Set(collapsibleItems); // Start with all items for each '+' group

                searchTerms.forEach((searchTerm, termIndex) => {
                    const currentFilteredItems = new Set();

                    filteredItems.forEach(item => {
                        const header = item.querySelector('.collapsible-header');
                        const body = item.querySelector('.collapsible-body');
                        let matchesTerm = false;

                        if (header) {
                            const headerText = header.textContent.toLowerCase();
                            if (headerText.includes(searchTerm)) {
                                matchesTerm = true;
                            }
                        }

                        if (body) {
                            const bodyText = body.textContent.toLowerCase();
                            if (bodyText.includes(searchTerm)) {
                                matchesTerm = true;
                            }
                        }

                        if (matchesTerm) {
                            currentFilteredItems.add(item);
                        }
                    });

                    if (termIndex === 0) {
                        filteredItems = new Set(currentFilteredItems); //set the first search term results as the current list to filter by
                    } else {
                        filteredItems = new Set([...filteredItems].filter(item => currentFilteredItems.has(item))); //filter out only the ones that match both
                    }

                });
                //combine filtered results
                if(commaIndex === 0){
                    finalFilteredItems = new Set(filteredItems) //set the first result to the final result
                } else {
                    finalFilteredItems = new Set([...finalFilteredItems, ...filteredItems]) //combine all results with the last results
                }
            });

            collapsibleItems.forEach(item => {
                item.style.display = finalFilteredItems.has(item) ? '' : 'none';
            });
        });
    }
    const weekSelectOptions = {
        format: "dd/mm/yyyy",
        i18n: {done: "Select"},
        setDefaultDate: true,
        autoClose: true,
        disableDayFn: function(date){
            if(date.getDay() == 6){
            return false;
            } else {
            return true;
            };
        },
        firstDay: 6,
        yearRange: 2,
        onSelect: function(date){
        // Set the input value explicitly
        this.el.value = M.Datepicker.getInstance(this.el).toString();
        // Submit the form
        this.el.closest('form').submit();
        },
        maxDate: new Date(),


    }

    const defaultOptions = {
        format: "dd/mm/yyyy",
        i18n: {done: "Select"},
        setDefaultDate: true,
        autoClose: true,
    }

    // datepicker initialization
    let datepickers = document.querySelectorAll('.datepicker');
    datepickers.forEach(picker => {
        if (picker.id === 'week_select') {
            M.Datepicker.init(picker, weekSelectOptions);
            const dateTrigger = document.querySelector('#date-trigger');
            dateTrigger.addEventListener('click', () => {
                M.Datepicker.getInstance(picker).open();
            });
        } else {
            M.Datepicker.init(picker, defaultOptions);
        }
    });



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
        // constrainWidth: false,
        // closeOnClick: false,
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

    // Loading spinner Javascript
    const preloaderBackground = document.querySelector('.preloader-background');
    const preloaderWrapper = document.querySelector('.preloader-wrapper');
    
    preloaderBackground.style.opacity = 0; // Start fading out
    preloaderBackground.style.transition = 'opacity 0.5s ease-in-out'; // Add a smooth transition

    preloaderWrapper.style.opacity = 0;
    preloaderWrapper.style.transition = 'opacity 0.5s ease-in-out';

    setTimeout(() => {
        preloaderBackground.style.display = 'none';
        preloaderWrapper.style.display = 'none';
    }, 500); // 500ms delay to ensure fade-out is complete

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


