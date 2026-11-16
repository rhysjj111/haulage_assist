// Run with: node --test tests/js/date-picker.test.cjs
// Exercise the real shared script without adding browser or package dependencies.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../haulage_app/static/js/script.js'), 'utf8');

class Element {
    constructor(id, value = '') {
        this.id = id;
        this.value = value;
        this.listeners = new Map();
        this.submissions = 0;
    }
    addEventListener(name, listener) {
        if (!this.listeners.has(name)) this.listeners.set(name, new Set());
        this.listeners.get(name).add(listener);
    }
    removeEventListener(name, listener) {
        this.listeners.get(name)?.delete(listener);
    }
    fire(name) {
        for (const listener of [...(this.listeners.get(name) || [])]) listener();
    }
    closest(selector) {
        assert.equal(selector, 'form');
        return {submit: () => { this.submissions += 1; }};
    }
}

function loadPage(pickers, withTrigger = false) {
    const document = new Element('document');
    const trigger = withTrigger ? new Element('date-trigger') : null;
    const initializations = [];
    const instances = new Map();
    document.querySelectorAll = selector => selector === '.datepicker' ? pickers : [];
    document.querySelector = selector => selector === '#date-trigger' ? trigger : null;
    document.getElementById = id => pickers.find(picker => picker.id === id) || null;
    const noopComponent = {init() {}};
    const M = {
        Collapsible: noopComponent,
        Sidenav: noopComponent,
        FormSelect: noopComponent,
        Dropdown: noopComponent,
        Datepicker: {
            getInstance: picker => instances.get(picker),
            init(picker, options) {
                const instance = {
                    el: picker,
                    options,
                    opened: 0,
                    selectedText: '',
                    open() { this.opened += 1; },
                    toString() { return this.selectedText; },
                };
                initializations.push({picker, options});
                instances.set(picker, instance);
                return instance;
            },
        },
    };
    const window = {addEventListener() {}, innerHeight: 900, innerWidth: 1440};
    vm.runInNewContext(source, {document, window, M, setTimeout, clearTimeout});
    document.fire('DOMContentLoaded');
    return {trigger, initializations, instance: picker => instances.get(picker)};
}

function parts(date) {
    return [date.getFullYear(), date.getMonth() + 1, date.getDate()];
}

test('fuel and payslip first focus initialize the remembered UK date as 11 September', () => {
    for (const form of ['fuel', 'payslip']) {
        const picker = new Element('date', '11/09/2026');
        const page = loadPage([picker]);
        assert.equal(page.initializations.length, 0, 'keep lazy initialization');
        picker.fire('focus');
        const options = page.instance(picker).options;
        assert.deepEqual(parts(options.defaultDate), [2026, 9, 11], form);
        assert.equal(options.format, 'dd/mm/yyyy');
        assert.equal(options.setDefaultDate, true);
        assert.equal(options.autoClose, true);
        assert.equal(options.openOnFocus, false);
        picker.fire('focus');
        assert.equal(page.initializations.length, 1);
    }
});

test('existing ISO dates initialize without changing their calendar day', () => {
    const picker = new Element('date', '2026-09-11');
    const page = loadPage([picker]);
    picker.fire('focus');
    assert.deepEqual(parts(page.instance(picker).options.defaultDate), [2026, 9, 11]);
});

test('parser reads ambiguous dates as UK dates, including subsequent edits', () => {
    const picker = new Element('date');
    const page = loadPage([picker]);
    picker.fire('focus');
    const parse = page.instance(picker).options.parse;
    for (const [value, expected] of [
        ['11/09/2026', [2026, 9, 11]],
        ['09/11/2026', [2026, 11, 9]],
        ['13/09/2026', [2026, 9, 13]],
        ['1/9/2026', [2026, 9, 1]],
        [' 11/09/2026 ', [2026, 9, 11]],
        ['2026-09-11', [2026, 9, 11]],
        ['29/02/2024', [2024, 2, 29]],
        ['2000-02-29', [2000, 2, 29]],
        ['01/01/0001', [1, 1, 1]], // Years below 100 must not silently gain 1900.
    ]) {
        assert.deepEqual(parts(parse(value, 'dd/mm/yyyy')), expected, value);
    }
});

test('parser rejects impossible dates and unsupported formats instead of guessing', () => {
    const picker = new Element('date');
    const page = loadPage([picker]);
    picker.fire('focus');
    const parse = page.instance(picker).options.parse;
    for (const value of [
        '', ' ', '11-09-2026', 'September 11, 2026', '11/09/26',
        '09/13/2026', '02/30/2026', '31/09/2026', '31/04/2026',
        '29/02/2026', '29/02/2100', '2026-02-29', '2026-09-31',
        '00/09/2026', '11/00/2026', '01/01/0000', '0000-01-01',
    ]) {
        assert.equal(parse(value, 'dd/mm/yyyy'), null, value);
    }
});

test('blank and rejected prefills cannot fall through to Materialize date guessing', () => {
    for (const value of ['', '31/09/2026', '02/30/2026', '09/13/2026']) {
        const picker = new Element('date', value);
        const page = loadPage([picker]);
        picker.fire('focus');
        const defaultDate = page.instance(picker).options.defaultDate;
        assert.ok(defaultDate, 'Materialize only falls back when defaultDate is falsy');
        assert.equal(Number.isNaN(defaultDate.getTime()), true, value);
    }
});

test('multiple entry and history pickers receive their own initial dates', () => {
    const first = new Element('date', '11/09/2026');
    const second = new Element('date', '09/11/2026');
    const page = loadPage([first, second]);
    first.fire('focus');
    second.fire('focus');
    const firstOptions = page.instance(first).options;
    const secondOptions = page.instance(second).options;
    assert.notEqual(firstOptions, secondOptions);
    assert.notEqual(firstOptions.defaultDate, secondOptions.defaultDate);
    assert.deepEqual(parts(firstOptions.defaultDate), [2026, 9, 11]);
    assert.deepEqual(parts(secondOptions.defaultDate), [2026, 11, 9]);
});

test('week selector focus and trigger paths use UK dates and retain Saturday selection', () => {
    for (const mode of ['focus', 'trigger']) {
        const picker = new Element('week_select', '12/09/2026');
        const page = loadPage([picker], true);
        if (mode === 'focus') picker.fire('focus');
        else page.trigger.fire('click');
        const instance = page.instance(picker);
        const options = instance.options;
        assert.deepEqual(parts(options.defaultDate), [2026, 9, 12], mode);
        assert.deepEqual(parts(options.parse('12/09/2026')), [2026, 9, 12]);
        assert.equal(options.firstDay, 6);
        assert.equal(options.autoClose, true);
        assert.equal(options.disableDayFn(new Date(2026, 8, 12)), false);
        assert.equal(options.disableDayFn(new Date(2026, 8, 13)), true);
        assert.ok(options.minDate < options.maxDate);
        assert.equal(picker.submissions, 0, 'initializing does not submit');
        instance.selectedText = '12/09/2026';
        options.onSelect.call(instance, new Date(2026, 8, 12));
        assert.equal(picker.value, '12/09/2026');
        assert.equal(picker.submissions, 1);
        page.trigger.fire('click');
        picker.fire('focus');
        assert.equal(page.initializations.length, 1);
        assert.ok(instance.opened > 0);
    }
});

test('pages without date fields continue to load', () => {
    assert.equal(loadPage([]).initializations.length, 0);
});
