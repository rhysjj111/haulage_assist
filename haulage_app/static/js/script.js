document.addEventListener('DOMContentLoaded', function () {
    // Debounce function
    function debounce(func, wait) {
        let timeout;
        return function() {
            const context = this;
            const args = arguments;
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(context, args), wait);
        };
    }  

    // collapsible initialization
    // const collapsibles = document.querySelectorAll('.collapsible');
    // M.Collapsible.init(collapsibles);

    // const collapsibleExpandable = document.querySelector('.collapsible.expandable');
    // M.Collapsible.init(collapsibleExpandable, {
    //     accordion: false
    // });

    const initCollapsiblesInView = () => {
        const collapsibles = document.querySelectorAll('.collapsible:not(.initialized)');
        collapsibles.forEach(collapsible => {
            const rect = collapsible.getBoundingClientRect();
            if (rect.top < window.innerHeight && rect.bottom > 0) {
                if (collapsible.classList.contains('expandable')) {
                    M.Collapsible.init(collapsible, {
                        accordion: false
                    });
                } else {
                    M.Collapsible.init(collapsible);
                }
                collapsible.classList.add('initialized');
            }
        });
    };

    // Initialize visible collapsibles on page load
    initCollapsiblesInView();
    // Initialize more as user scrolls
    window.addEventListener('scroll', debounce(initCollapsiblesInView, 100), { passive: true });
    
    function filterCollapsibleItems(parentSelector, collapsibleItems) {
        const parent = document.querySelector(parentSelector);
        let debounceTimer;

        if (parent) {
            parent.addEventListener('input', function (event) {
                if (event.target.id === 'search-entries') {
                    // Clear previous timer
                    clearTimeout(debounceTimer);
                    
                    // Set a new timer to delay filtering
                    debounceTimer = setTimeout(() => {
                        const searchValue = event.target.value.trim();
                        
                        // Only perform filtering if there's actually a search term
                        if (searchValue) {
                            performFiltering(searchValue);
                        } else {
                            // If search is empty, show all items
                            collapsibleItems.forEach(item => {
                                item.style.display = '';
                            });
                        }
                    }, 300); // 300ms delay before filtering
                }
            });
    
            // Initial filtering on page load only if there's a value
            const searchInput = parent.querySelector('#search-entries');
            if (searchInput && searchInput.value.trim()) {
                performFiltering(searchInput.value);
            }
        }

        function performFiltering(inputValue) {
            const inputString = inputValue.toLowerCase();
            const commaSplitTerms = inputString.split('+');

            let finalFilteredItems = new Set();

            commaSplitTerms.forEach((commaSplitTerm, commaIndex) => {
                const searchTerms = commaSplitTerm.split(',').map(term => term.trim()).filter(term => term !== "");
                let filteredItems = new Set(collapsibleItems);

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
                        filteredItems = new Set(currentFilteredItems);
                    } else {
                        filteredItems = new Set([...filteredItems].filter(item => currentFilteredItems.has(item)));
                    }
                });

                if (commaIndex === 0) {
                    finalFilteredItems = new Set(filteredItems);
                } else {
                    finalFilteredItems = new Set([...finalFilteredItems, ...filteredItems]);
                }
            });

            collapsibleItems.forEach(item => {
                item.style.display = finalFilteredItems.has(item) ? '' : 'none';
            });
        }
    }

    const collapsibleItems = document.querySelectorAll('.collapsible li');
    filterCollapsibleItems('.entry-history', collapsibleItems);

    // const weekSelectOptions = {
    //     format: "dd/mm/yyyy",
    //     i18n: {done: "Select"},
    //     setDefaultDate: true,
    //     autoClose: true,
    //     disableDayFn: function(date){
    //         if(date.getDay() == 6){
    //         return false;
    //         } else {
    //         return true;
    //         };
    //     },
    //     firstDay: 6,
    //     yearRange: 2,
    //     onSelect: function(date){
    //     // Set the input value explicitly
    //     this.el.value = M.Datepicker.getInstance(this.el).toString();
    //     // Submit the form
    //     this.el.closest('form').submit();
    //     },
    //     maxDate: new Date(),


    // }

    // const defaultOptions = {
    //     format: "dd/mm/yyyy",
    //     i18n: {done: "Select"},
    //     setDefaultDate: true,
    //     autoClose: true,
    // }

    // 7. Specific Datepicker Optimization
    // Pre-calculate dates to avoid recalculation during rendering
    const today = new Date();
    const maxDate = new Date(today);
    const minDate = new Date(today);
    minDate.setFullYear(today.getFullYear() - 2);

    const weekSelectOptions = {
        format: "dd/mm/yyyy",
        i18n: {done: "Select"},
        setDefaultDate: true,
        autoClose: true,
        disableDayFn: date => date.getDay() !== 6, // Simplified logic
        firstDay: 6,
        yearRange: 2,
        minDate: minDate,
        maxDate: maxDate,
        onSelect: function(date){
            // Set the input value explicitly
            this.el.value = M.Datepicker.getInstance(this.el).toString();
            // Submit the form
            this.el.closest('form').submit();
        }
    }

    const defaultOptions = {
        format: "dd/mm/yyyy",
        i18n: {done: "Select"},
        setDefaultDate: true,
        autoClose: true,
        openOnFocus: false,
    }   

    // datepicker initialization
    // let datepickers = document.querySelectorAll('.datepicker');
    // datepickers.forEach(picker => {
    //     // Only initialize when needed
    //     const initDatepicker = () => {
    //         if (picker.id === 'week_select') {
    //             M.Datepicker.init(picker, weekSelectOptions);
    //         } else {
    //             M.Datepicker.init(picker, defaultOptions);
    //         }
    //         // Remove event listener after initialization
    //         picker.removeEventListener('focus', initDatepicker);
    //     };
        
    //     // Initialize on focus instead of on page load
    //     picker.addEventListener('focus', initDatepicker);
        
    //     // For week_select, handle the trigger button
    //     if (picker.id === 'week_select') {
    //         const dateTrigger = document.querySelector('#date-trigger');
    //         if (dateTrigger) {
    //             dateTrigger.addEventListener('click', () => {
    //                 // Initialize if not already done
    //                 if (!M.Datepicker.getInstance(picker)) {
    //                     M.Datepicker.init(picker, weekSelectOptions);
    //                 }
    //                 M.Datepicker.getInstance(picker).open();
    //             });
    //         }
    //     }
    // });
    // Find the input element with the class 'datepicker'
    const datepickers = document.querySelectorAll('.datepicker');

    // Find the input element with the class 'datepicker'
    const datepickerInput = document.querySelector('.datepicker');

    // Check if the element exists to prevent errors
    if (datepickerInput) {
        // Set the focus on the found input field
        datepickerInput.focus();
    } 

    datepickers.forEach(picker => {
        // Only initialize when needed
        const initDatepicker = () => {
            if (picker.id === 'week_select') {
                if (!M.Datepicker.getInstance(picker)) {
                    M.Datepicker.init(picker, weekSelectOptions);
                }
            } else {
                if (!M.Datepicker.getInstance(picker)) {
                    M.Datepicker.init(picker, defaultOptions);
                }
            }
            // Remove event listener after initialization
            picker.removeEventListener('focus', initDatepicker);
        };
        
        // Initialize on focus instead of on page load
        picker.addEventListener('focus', initDatepicker);
    });
    
    // Special handling for week_select
    const weekSelect = document.getElementById('week_select');
    const dateTrigger = document.querySelector('#date-trigger');
    if (weekSelect && dateTrigger) {
        dateTrigger.addEventListener('click', () => {
            // Initialize if not already done
            if (!M.Datepicker.getInstance(weekSelect)) {
                M.Datepicker.init(weekSelect, weekSelectOptions);
            }
            M.Datepicker.getInstance(weekSelect).open();
        });
    }



    // sidenav initialization
    let sidenavigation = document.querySelectorAll('.sidenav');
    M.Sidenav.init(sidenavigation);


    // // modal initialisation
    // let modal = document.querySelectorAll('.modal');
    // M.Modal.init(modal, {
    //     endingTop: '10%',
    //     preventScrolling: false,
    //     onOpenEnd: function(modal) {
    //         // If this is a week modal, focus on the first start mileage field
    //         if (modal.classList.contains('week-modal')) {
    //             const firstStartMileage = modal.querySelector('input[name$="start_mileage"]');
    //             if (firstStartMileage && !firstStartMileage.disabled) {
    //                 setTimeout(() => {
    //                     firstStartMileage.focus();
    //                     firstStartMileage.select(); // Select text if any
    //                 }, 100); // Small delay to ensure modal is fully rendered
    //             }
    //         }
    //     }
    // });
    
    // // edit-modal re-open when invalid form submission
    // let modalOpen = document.querySelector('.open-modal')
    // if (modalOpen){
    //     modalOpen = modalOpen.textContent;
    //     modalOpen = document.querySelector(`#${modalOpen}`);
    //     M.Modal.init(modalOpen).open();
    // };

    // 2. Optimize Modal Initialization
    // Lazy initialization for modals
    const modalTriggers = document.querySelectorAll('[data-target^="modal"], .modal-trigger');
    modalTriggers.forEach(trigger => {
        trigger.addEventListener('click', () => {
            const modalId = trigger.getAttribute('data-target') || trigger.getAttribute('href');
            if (!modalId) return;
            
            const modal = document.querySelector(modalId);
            if (modal && !M.Modal.getInstance(modal)) {
                M.Modal.init(modal, {
                    endingTop: '10%',
                    preventScrolling: false,
                    onOpenEnd: function(modal) {
                        if (modal.classList.contains('week-modal')) {
                            const firstStartMileage = modal.querySelector('input[name$="start_mileage"]');
                            if (firstStartMileage && !firstStartMileage.disabled) {
                                setTimeout(() => {
                                    firstStartMileage.focus();
                                    firstStartMileage.select();
                                }, 100);
                            }
                        }
                    }
                });
            }
            M.Modal.getInstance(modal).open();
        });
    });
    
    // Handle edit-modal re-open when invalid form submission
    let modalOpen = document.querySelector('.open-modal')
    if (modalOpen){
        const modalId = modalOpen.textContent;
        const modal = document.querySelector(`#${modalId}`);
        if (modal && !M.Modal.getInstance(modal)) {
            M.Modal.init(modal, {
                endingTop: '10%',
                preventScrolling: false
            });
        }
        M.Modal.getInstance(modal).open();
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

    if (preloaderBackground && preloaderWrapper) {
        // Use requestAnimationFrame for smoother transitions
        requestAnimationFrame(() => {
            preloaderBackground.style.opacity = 0;
            preloaderBackground.style.transition = 'opacity 0.5s ease-in-out';
            
            preloaderWrapper.style.opacity = 0;
            preloaderWrapper.style.transition = 'opacity 0.5s ease-in-out';
            
            // Use transitionend instead of setTimeout when possible
            preloaderBackground.addEventListener('transitionend', () => {
                preloaderBackground.style.display = 'none';
                preloaderWrapper.style.display = 'none';
            }, { once: true });
        });
    }
    
    // preloaderBackground.style.opacity = 0; // Start fading out
    // preloaderBackground.style.transition = 'opacity 0.5s ease-in-out'; // Add a smooth transition

    // preloaderWrapper.style.opacity = 0;
    // preloaderWrapper.style.transition = 'opacity 0.5s ease-in-out';

    // setTimeout(() => {
    //     preloaderBackground.style.display = 'none';
    //     preloaderWrapper.style.display = 'none';
    // }, 500); // 500ms delay to ensure fade-out is complete

    // Function to handle disabling fields based on status in week modals
    function setupWeekModalStatusHandlers() {
        const weekModals = document.querySelectorAll('.week-modal');
        
        weekModals.forEach(modal => {
            const statusSelects = modal.querySelectorAll('select[name$="status"]');
            
            statusSelects.forEach(statusSelect => {
                // Get the prefix from the select name (format: prefix-date-status)
                const nameParts = statusSelect.name.split('-');
                const prefix = nameParts.slice(0, nameParts.length - 1).join('-');
                
                // Find all related fields in the same row
                const row = statusSelect.closest('tr');
                const fieldsToToggle = row.querySelectorAll(`
                    input[name^="${prefix}"][name$="start_mileage"],
                    input[name^="${prefix}"][name$="end_mileage"],
                    input[name^="${prefix}"][name$="overnight"],
                    input[name^="${prefix}"][name$="fuel"],
                    select[name^="${prefix}"][name$="truck"]
                `);
                
                // Initial setup on page load
                toggleFieldsBasedOnStatus(statusSelect.value, fieldsToToggle);
                
                // Add event listener for status changes
                statusSelect.addEventListener('change', function() {
                    toggleFieldsBasedOnStatus(this.value, fieldsToToggle);
                    
                    // Reinitialize Materialize selects if they're disabled/enabled
                    const truckSelect = row.querySelector(`select[name^="${prefix}"][name$="truck"]`);
                    if (truckSelect) {
                        M.FormSelect.init(truckSelect);
                    }
                });
            });
        });
    }
    
    function toggleFieldsBasedOnStatus(status, fields) {
        const shouldEnable = (status === 'working');
        
        fields.forEach(field => {
            field.disabled = !shouldEnable;
            
            // For checkboxes and other inputs, add visual indication
            if (field.type === 'checkbox') {
                const label = field.closest('label');
                if (label) {
                    if (shouldEnable) {
                        label.classList.remove('disabled');
                    } else {
                        label.classList.add('disabled');
                    }
                }
            } else {
                // For text inputs and selects
                const inputField = field.closest('.input-field');
                if (inputField) {
                    if (shouldEnable) {
                        inputField.classList.remove('disabled');
                    } else {
                        inputField.classList.add('disabled');
                    }
                }
            }
        });
    }

    setupWeekModalStatusHandlers();

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


