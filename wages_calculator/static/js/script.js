document.addEventListener('DOMContentLoaded', function() {
    // collapsible initialization
    const collapsibles = document.querySelectorAll('.collapsible');
    M.Collapsible.init(collapsibles);

    // datepicker initialization
    let datepicker = document.querySelectorAll('.datepicker');
    M.Datepicker.init(datepicker, {
        format: "dd mmmm, yyyy",
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

    // modal initialisation
    let modal = document.querySelectorAll('.modal');
    M.Modal.init(modal);

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
    
    //flash feedback timeout and remove container after a time interval
    const messageContainer = document.querySelector(".messages-container");
    setInterval(() => messageContainer.style.opacity = '0', 5000);
    messageContainer.addEventListener('transitionend', () => messageContainer.remove());
});
