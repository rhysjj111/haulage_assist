(function () {
    'use strict';

    document.querySelectorAll('form[data-owner-period-picker]').forEach(function (form) {
        var picker = form.querySelector('[data-owner-period-input]');
        if (!picker) return;
        var originalValue = picker.value;
        var navigating = false;

        picker.addEventListener('click', function () {
            if (typeof picker.showPicker === 'function') {
                try { picker.showPicker(); } catch (error) { /* Keep the native control available. */ }
            }
        });

        picker.addEventListener('change', function () {
            if (navigating || !picker.value || picker.value === originalValue || !form.checkValidity()) return;
            navigating = true;
            if (typeof form.requestSubmit === 'function') form.requestSubmit();
            else form.submit();
        });

        window.addEventListener('pageshow', function (event) {
            if (event.persisted) {
                picker.value = originalValue;
                navigating = false;
            }
        });
    });
}());
