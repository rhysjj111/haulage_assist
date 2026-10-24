/* Uploaded bytes and review edits live only in this page's memory. */
(() => {
    "use strict";

    const root = document.getElementById("fuel-import");
    if (!root) return;
    const byId = (id) => document.getElementById(id);
    const fileInput = byId("fuel-xlsx-file");
    const readButton = byId("fuel-read-xlsx");
    const clearButton = byId("fuel-clear-xlsx");
    const status = byId("fuel-import-status");
    const errorBox = byId("fuel-import-error");
    const review = byId("fuel-import-review");
    const tableBody = byId("fuel-transaction-rows");
    const previousPage = byId("fuel-previous-page");
    const nextPage = byId("fuel-next-page");
    const maxBytes = 10 * 1024 * 1024;
    const pageSize = 100;
    const xlsxType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    const knownIssues = new Set([
        "missing_transaction_registration", "registration_mismatch", "unsupported_product",
        "non_positive_quantity", "non_positive_cost", "cost_price_mismatch",
    ]);
    const knownMatchStates = new Set([
        "matched", "unmatched", "ambiguous", "registration_conflict", "missing_registration",
    ]);
    const issueLabels = {
        missing_transaction_registration: "No transaction registration in the source.",
        registration_mismatch: "Transaction and card registrations differ.",
        unsupported_product: "Review product; excluded by default.",
        non_positive_quantity: "Source litres are zero or negative.",
        non_positive_cost: "Source cost is zero or negative.",
        cost_price_mismatch: "Source cost differs from quantity × unit price.",
    };
    let chosenFile = null;
    let controller = null;
    let generation = 0;
    let busy = false;
    let rows = [];
    let trucks = [];
    let truckIds = new Set();
    let page = 0;

    function node(tag, className, text) {
        const element = document.createElement(tag);
        if (className) element.className = className;
        if (text !== undefined) element.textContent = text;
        return element;
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
    }

    function clearError() {
        errorBox.textContent = "";
        errorBox.hidden = true;
    }

    function setBusy(value) {
        busy = value;
        readButton.disabled = value || !chosenFile;
        readButton.textContent = value ? "Reading…" : "Read spreadsheet";
        root.setAttribute("aria-busy", String(value));
    }

    function resetPreview() {
        rows = [];
        trucks = [];
        truckIds = new Set();
        page = 0;
        tableBody.replaceChildren();
        review.hidden = true;
        byId("fuel-review-pager").hidden = true;
        byId("fuel-selection-summary").textContent = "";
        byId("fuel-selected-totals").textContent = "";
    }

    function cancelReading() {
        generation += 1;
        if (controller) controller.abort();
        controller = null;
        setBusy(false);
    }

    function parseHundredths(value, signed = false) {
        if (typeof value !== "string" || value.length > 32) return null;
        // Totals may contain more digits than an individual source amount.
        const pattern = signed ? /^-?\d{1,16}(?:\.\d{1,2})?$/ : /^\d{1,16}(?:\.\d{1,2})?$/;
        if (!pattern.test(value)) return null;
        const negative = value.startsWith("-");
        const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
        const amount = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
        return negative ? -amount : amount;
    }

    function displayHundredths(value) {
        const negative = value < 0n;
        const unsigned = negative ? -value : value;
        const whole = String(unsigned / 100n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
        return `${negative ? "−" : ""}${whole}.${String(unsigned % 100n).padStart(2, "0")}`;
    }

    function validDate(value) {
        if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
        const [year, month, day] = value.split("-").map(Number);
        if (!year || month < 1 || month > 12 || day < 1) return false;
        const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
        return day <= [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
    }

    function fieldError(model, field) {
        if (field === "date") return validDate(model.date) ? "" : "Choose a valid purchase date.";
        if (field === "truck") return truckIds.has(model.truckId) ? "" : "Choose a truck.";
        const value = parseHundredths(model[field]);
        if (value === null) return "Use a positive number with up to two decimal places.";
        if (field === "quantity" && (value <= 100n || value >= 100000n)) return "Use more than 1 and less than 1,000 litres.";
        if (field === "cost" && (value <= 100n || value >= 150000n)) return "Use more than £1 and less than £1,500.";
        return "";
    }

    function updateField(model, field, input, error) {
        const message = model.included ? fieldError(model, field) : "";
        input.setAttribute("aria-invalid", String(Boolean(message)));
        error.textContent = message;
        error.hidden = !message;
    }

    function updateSummary() {
        const included = rows.filter((model) => model.included);
        let invalid = 0;
        let quantity = 0n;
        let cost = 0n;
        let invalidAmounts = false;
        for (const model of included) {
            if (["date", "truck", "quantity", "cost"].some((field) => fieldError(model, field))) invalid += 1;
            const litres = parseHundredths(model.quantity);
            const amount = parseHundredths(model.cost);
            if (litres === null || amount === null || fieldError(model, "quantity") || fieldError(model, "cost")) {
                invalidAmounts = true;
            } else {
                quantity += litres;
                cost += amount;
            }
        }
        const excluded = rows.length - included.length;
        byId("fuel-selection-summary").textContent = `${included.length} of ${rows.length} entries selected · ${excluded} excluded${invalid ? ` · ${invalid} selected ${invalid === 1 ? "entry needs" : "entries need"} attention` : ""}`;
        byId("fuel-selected-totals").textContent = invalidAmounts
            ? "Selected totals: correct litres and cost first."
            : `Selected totals: ${displayHundredths(quantity)} L · £${displayHundredths(cost)}`;
    }

    function addOriginalField(list, label, value) {
        const item = node("div");
        item.append(node("dt", "", label), node("dd", "", value || "—"));
        list.append(item);
    }

    function createOriginalRow(source, sourceButton) {
        const originalRow = node("tr", "fuel-import-original-row");
        originalRow.id = `fuel-original-row-${source.source_row}`;
        originalRow.hidden = true;
        const cell = node("td");
        cell.colSpan = 6;
        const box = node("section", "fuel-import-original");
        const heading = node("h3", "", `Original spreadsheet row ${source.source_row}`);
        const list = node("dl");
        addOriginalField(list, "Purchase date", source.transaction_date);
        addOriginalField(list, "Time", source.transaction_time);
        addOriginalField(list, "Tran VRN", source.transaction_registration);
        addOriginalField(list, "Card VRN", source.card_registration);
        addOriginalField(list, "Card Type / network", source.card_type);
        addOriginalField(list, "Product", source.product);
        addOriginalField(list, "Quantity (litres)", source.quantity);
        addOriginalField(list, "Cost (£)", source.cost);
        addOriginalField(list, "Unit Price (£/litre)", source.unit_price);
        box.append(heading, list);
        cell.append(box);
        originalRow.append(cell);
        sourceButton.setAttribute("aria-controls", originalRow.id);
        sourceButton.setAttribute("aria-expanded", "false");
        sourceButton.addEventListener("click", () => {
            originalRow.hidden = !originalRow.hidden;
            sourceButton.setAttribute("aria-expanded", String(!originalRow.hidden));
            sourceButton.textContent = `${originalRow.hidden ? "Original" : "Hide original"} row ${source.source_row}`;
        });
        return originalRow;
    }

    function createField(model, field, label) {
        const cell = node("td");
        const input = node("input");
        const error = node("span", "fuel-import-field-error");
        input.id = `fuel-row-${model.source.source_row}-${field}`;
        error.id = `${input.id}-error`;
        input.setAttribute("aria-label", `${label}, row ${model.source.source_row}`);
        input.setAttribute("aria-describedby", error.id);
        if (field === "date") {
            input.type = "date";
            input.min = "0001-01-01";
            input.max = "9999-12-31";
        } else {
            input.type = "text";
            input.inputMode = "decimal";
            input.autocomplete = "off";
            input.maxLength = 32;
            cell.className = "fuel-import-number";
        }
        input.value = model[field];
        input.addEventListener("input", () => {
            model[field] = input.value;
            updateField(model, field, input, error);
            updateSummary();
        });
        input.addEventListener("blur", () => {
            // A canonical value on blur keeps the editable figures at 2dp.
            if (field !== "date" && !fieldError(model, field)) {
                const amount = parseHundredths(model[field]);
                model[field] = `${amount / 100n}.${String(amount % 100n).padStart(2, "0")}`;
                input.value = model[field];
            }
        });
        cell.append(input, error);
        return {cell, input, error, field};
    }

    function createTruckField(model) {
        const cell = node("td");
        const select = node("select", "browser-default");
        select.id = `fuel-row-${model.source.source_row}-truck`;
        select.setAttribute("aria-label", `Truck, row ${model.source.source_row}`);
        const error = node("span", "fuel-import-field-error");
        error.id = `${select.id}-error`;
        select.setAttribute("aria-describedby", error.id);
        const placeholder = node("option", "", "Choose truck…");
        placeholder.value = "";
        select.append(placeholder);
        for (const truck of trucks) {
            const option = node("option", "", truck.registration);
            option.value = String(truck.id);
            select.append(option);
        }
        select.value = model.truckId === null ? "" : String(model.truckId);
        select.addEventListener("change", () => {
            model.truckId = select.value ? Number(select.value) : null;
            updateField(model, "truck", select, error);
            updateSummary();
        });
        cell.append(select, error);
        const matchNotes = {
            unmatched: "No matching truck; choose one to include.",
            ambiguous: "More than one truck matches; choose one.",
            registration_conflict: "Source registrations differ; choose the correct truck.",
            missing_registration: "No transaction registration; choose a truck.",
        };
        if (matchNotes[model.source.match_status]) cell.append(node("p", "fuel-import-source-warning", matchNotes[model.source.match_status]));
        return {cell, input: select, error, field: "truck"};
    }

    function createRow(model) {
        const source = model.source;
        const row = node("tr");
        row.dataset.sourceRow = String(source.source_row);
        const includeCell = node("td", "fuel-import-include-column");
        const checkbox = node("input");
        checkbox.type = "checkbox";
        checkbox.checked = model.included;
        checkbox.setAttribute("aria-label", `Include spreadsheet row ${source.source_row}`);
        includeCell.append(checkbox);
        const sourceCell = node("td");
        sourceCell.append(node("span", "fuel-import-source-registration", source.transaction_registration || "No registration"));
        sourceCell.append(node("span", "fuel-import-source-meta", [source.product, source.card_type].filter(Boolean).join(" · ")));
        const sourceButton = node("button", "fuel-import-text-button fuel-import-original-button", `Original row ${source.source_row}`);
        sourceButton.type = "button";
        sourceCell.append(sourceButton);
        for (const issue of source.issues) {
            if (issue !== "missing_transaction_registration" && issue !== "registration_mismatch") {
                sourceCell.append(node("p", "fuel-import-source-warning", issueLabels[issue]));
            }
        }
        const fields = [createField(model, "date", "Purchase date"), createTruckField(model),
            createField(model, "quantity", "Litres"), createField(model, "cost", "Cost in pounds")];
        const update = () => {
            row.classList.toggle("fuel-import-excluded", !model.included);
            for (const field of fields) updateField(model, field.field, field.input, field.error);
        };
        checkbox.addEventListener("change", () => {
            model.included = checkbox.checked;
            update();
            updateSummary();
        });
        row.append(includeCell, sourceCell, ...fields.map((field) => field.cell));
        update();
        return [row, createOriginalRow(source, sourceButton)];
    }

    function renderPage() {
        const start = page * pageSize;
        const shown = rows.slice(start, start + pageSize);
        const fragment = document.createDocumentFragment();
        for (const model of shown) fragment.append(...createRow(model));
        tableBody.replaceChildren(fragment);
        byId("fuel-review-pager").hidden = rows.length <= pageSize;
        previousPage.disabled = page === 0;
        nextPage.disabled = start + pageSize >= rows.length;
        byId("fuel-page-description").textContent = `Entries ${start + 1}–${Math.min(start + pageSize, rows.length)} of ${rows.length}`;
    }

    function validString(value, nullable = false) {
        return (nullable && value === null) || (typeof value === "string" && value.length <= 1000);
    }

    function validPayload(data) {
        if (!data || typeof data !== "object" || !data.report || !Array.isArray(data.rows)
                || !Array.isArray(data.trucks) || !data.rows.length || data.rows.length > 10000
                || data.trucks.length > 10000) return false;
        const report = data.report;
        if (report.source_format !== "fuel-store-transactions-xlsx-v1"
                || report.fuel_card_name !== "The Fuel Store" || !validString(report.sheet_name)
                || !Number.isInteger(report.header_row) || report.header_row < 1
                || report.transaction_count !== data.rows.length || !report.totals
                || parseHundredths(report.totals.quantity, true) === null
                || parseHundredths(report.totals.cost, true) === null) return false;
        const ids = new Set();
        for (const truck of data.trucks) {
            if (!truck || !Number.isSafeInteger(truck.id) || truck.id <= 0 || ids.has(truck.id)
                    || !validString(truck.registration)) return false;
            ids.add(truck.id);
        }
        const sourceRows = new Set();
        let quantity = 0n;
        let cost = 0n;
        for (const source of data.rows) {
            if (!source || !Number.isInteger(source.source_row) || source.source_row < 1
                    || sourceRows.has(source.source_row) || !validDate(source.transaction_date)
                    || !(source.transaction_time === null || (typeof source.transaction_time === "string"
                        && /^\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$/.test(source.transaction_time)))
                    || !validString(source.transaction_registration, true)
                    || !validString(source.card_registration, true) || !validString(source.card_type)
                    || !validString(source.product) || parseHundredths(source.quantity, true) === null
                    || parseHundredths(source.cost, true) === null || typeof source.unit_price !== "string"
                    || source.unit_price.length > 64 || !/^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(source.unit_price)
                    || !Array.isArray(source.issues) || source.issues.length > knownIssues.size
                    || !source.issues.every((issue) => knownIssues.has(issue))
                    || !knownMatchStates.has(source.match_status)
                    || !(source.truck_id === null || ids.has(source.truck_id))
                    || !Array.isArray(source.candidate_truck_ids)
                    || !source.candidate_truck_ids.every((id) => ids.has(id))) return false;
            sourceRows.add(source.source_row);
            quantity += parseHundredths(source.quantity, true);
            cost += parseHundredths(source.cost, true);
        }
        return quantity === parseHundredths(report.totals.quantity, true)
            && cost === parseHundredths(report.totals.cost, true);
    }

    function showPreview(data) {
        if (!validPayload(data)) throw new Error("invalid_preview");
        trucks = data.trucks;
        truckIds = new Set(trucks.map((truck) => truck.id));
        rows = data.rows.map((source) => {
            const unsafeDefault = ["missing_transaction_registration", "registration_mismatch", "unsupported_product",
                "non_positive_quantity", "non_positive_cost"].some((issue) => source.issues.includes(issue));
            const model = {source: Object.freeze({...source, issues: Object.freeze([...source.issues])}),
                date: source.transaction_date, truckId: source.truck_id,
                quantity: source.quantity, cost: source.cost,
                included: source.match_status === "matched" && source.truck_id !== null && !unsafeDefault};
            // Out-of-range source amounts remain visible and need a deliberate
            // inclusion after correction; no source rows disappear.
            if (["date", "truck", "quantity", "cost"].some((field) => fieldError(model, field))) model.included = false;
            return model;
        });
        byId("fuel-report-description").textContent = `${data.report.fuel_card_name} · ${data.report.sheet_name} · ${data.rows.length} ${data.rows.length === 1 ? "transaction" : "transactions"}`;
        byId("fuel-source-totals").textContent = `Spreadsheet totals (calculated): ${displayHundredths(parseHundredths(data.report.totals.quantity, true))} L · £${displayHundredths(parseHundredths(data.report.totals.cost, true))}`;
        page = 0;
        renderPage();
        updateSummary();
        review.hidden = false;
    }

    fileInput.addEventListener("change", () => {
        cancelReading();
        resetPreview();
        clearError();
        status.textContent = "";
        chosenFile = fileInput.files && fileInput.files[0] || null;
        clearButton.hidden = !chosenFile;
        if (chosenFile && (!/\.xlsx$/i.test(chosenFile.name) || chosenFile.size === 0)) {
            showError("Choose The Fuel Store's Transactions .xlsx export.");
            chosenFile = null;
        } else if (chosenFile && chosenFile.size > maxBytes) {
            showError("The spreadsheet is too large. Choose a file under 10 MB.");
            chosenFile = null;
        }
        setBusy(false);
    });

    clearButton.addEventListener("click", () => {
        cancelReading();
        resetPreview();
        clearError();
        chosenFile = null;
        fileInput.value = "";
        clearButton.hidden = true;
        status.textContent = "";
        setBusy(false);
    });

    readButton.addEventListener("click", async () => {
        if (!chosenFile || busy) return;
        cancelReading();
        resetPreview();
        clearError();
        const currentGeneration = generation;
        const upload = chosenFile;
        controller = new AbortController();
        setBusy(true);
        status.textContent = "Reading the spreadsheet…";
        try {
            const response = await fetch(root.dataset.readUrl, {
                method: "POST",
                headers: {"Content-Type": xlsxType, "X-CSRFToken": root.dataset.csrfToken},
                body: upload, credentials: "same-origin", cache: "no-store", signal: controller.signal,
            });
            if (generation !== currentGeneration) return;
            const data = await response.json();
            if (generation !== currentGeneration) return;
            if (!response.ok) {
                const message = data && data.error && data.error.message;
                showError(typeof message === "string" && message.length <= 500
                    ? message : "The spreadsheet could not be read. Try the original Transactions export.");
                status.textContent = "";
                return;
            }
            showPreview(data);
            status.textContent = "Spreadsheet read. Review the entries below.";
        } catch (error) {
            if (generation !== currentGeneration || error.name === "AbortError") return;
            resetPreview();
            status.textContent = "";
            showError("The spreadsheet could not be read. Check your connection and try again.");
        } finally {
            if (generation === currentGeneration) {
                controller = null;
                setBusy(false);
            }
        }
    });

    previousPage.addEventListener("click", () => {
        if (page <= 0) return;
        page -= 1;
        renderPage();
    });
    nextPage.addEventListener("click", () => {
        if ((page + 1) * pageSize >= rows.length) return;
        page += 1;
        renderPage();
    });
    window.addEventListener("pagehide", () => {
        cancelReading();
        resetPreview();
        chosenFile = null;
        fileInput.value = "";
        clearButton.hidden = true;
        status.textContent = "";
        clearError();
        setBusy(false);
    });
})();
