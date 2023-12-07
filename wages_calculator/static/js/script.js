document.addEventListener('DOMContentLoaded', function() {
    // collapsible initialization
    const collapsibles = document.querySelectorAll('.collapsible');
    M.Collapsible.init(collapsibles);

    // datepicker initialization
    let datepicker = document.querySelectorAll('.datepicker');
    M.Datepicker.init(datepicker, {
        format: "dd mmmm, yyyy",
        i18n: {done: "Select"}
    })

    function removeTabs() {
        const subTabs = document.querySelector('#sub-menu-tabs') 
        const tabs = M.Tabs.init(subTabs, swipeable=true);
        if(window.innerWidth > 992){
            tabs.destroy();
        } else {
            tabs;
        }
    }
    window.onresize = removeTabs;
    removeTabs();
    
});
