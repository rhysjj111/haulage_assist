/* Temporary document and editable preview state stay in this page's memory. */
(() => {
    "use strict";

    const root = document.getElementById("payroll-import");
    if (!root) return;
    const byId = (id) => document.getElementById(id);
    const fileInput = byId("payroll-pdf-file");
    const readButton = byId("payroll-read-pdf");
    const clearButton = byId("payroll-clear-pdf");
    const review = byId("payroll-import-review");
    const errorBox = byId("payroll-import-error");
    const status = byId("payroll-import-status");
    const driverRows = byId("payroll-driver-rows");
    const otherRows = byId("payroll-other-rows");
    const others = byId("payroll-other-employees");
    const weekInput = byId("payroll-week-start");
    const iframe = byId("payroll-pdf-preview");
    const openLink = byId("payroll-open-pdf");
    const checkStatus = byId("payroll-existing-check-status");
    const retryChecks = byId("payroll-retry-checks");
    const saveButton = byId("payroll-save-payslips");
    const saveStatus = byId("payroll-save-status");
    const saveResult = byId("payroll-save-result");
    const savedHistory = byId("payroll-saved-history");
    const maxBytes = 10 * 1024 * 1024;
    const dateFormat = new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
    let chosenFile = null;
    let documentUrl = null;
    let controller = null;
    let generation = 0;
    let busy = false;
    let visiblePage = 1;
    let rowModels = [];
    let checkController = null;
    let checkTimer = null;
    let checkGeneration = 0;
    let checkKey = null;
    let checkPhase = "idle";
    let existingByDriver = new Map();
    let daysByDriver = new Map();
    let savePhase = "idle";
    let saveReady = false;
    let saveGeneration = 0;

    function editingLocked() {
        return savePhase === "saving" || savePhase === "complete";
    }

    function updateControlLocks() {
        const saving = savePhase === "saving";
        fileInput.disabled = saving;
        clearButton.disabled = saving;
        readButton.disabled = busy || editingLocked() || !chosenFile;
        weekInput.disabled = editingLocked();
        retryChecks.disabled = saving || savePhase === "complete";
        saveButton.disabled = !saveReady || editingLocked();
        const count = rowModels.filter((model) => model.row.parentElement === driverRows).length;
        saveButton.textContent = saving ? "Saving…" : savePhase === "complete" ? "Saved" : `Save ${count || ""}${count ? " " : ""}${count === 1 ? "payslip" : "payslips"}`;
        for (const model of rowModels) {
            model.select.disabled = editingLocked();
            const included = model.row.parentElement === driverRows;
            model.wage.input.disabled = editingLocked() || !included;
            model.cost.input.disabled = editingLocked() || !included;
        }
        root.setAttribute("aria-busy", String(busy || saving));
    }

    function setBusy(value) {
        busy = value;
        readButton.textContent = value ? "Reading…" : "Read PDF";
        updateControlLocks();
    }

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = false;
    }

    function clearError() {
        errorBox.textContent = "";
        errorBox.hidden = true;
    }

    function releaseDocument() {
        iframe.removeAttribute("src");
        openLink.removeAttribute("href");
        if (documentUrl) URL.revokeObjectURL(documentUrl);
        documentUrl = null;
    }

    function createDocumentUrl(file) {
        // A file's supplied MIME type must never turn this preview into HTML.
        return URL.createObjectURL(new Blob([file], {type: "application/pdf"}));
    }

    function showPage(page) {
        visiblePage = Number.isInteger(page) && page > 0 ? page : 1;
        if (!documentUrl) return;
        const url = `${documentUrl}#page=${visiblePage}&view=FitH`;
        iframe.src = url;
        openLink.href = url;
    }

    function resetPreview() {
        cancelCheckWork();
        checkKey = null;
        checkPhase = "idle";
        existingByDriver = new Map();
        daysByDriver = new Map();
        saveGeneration += 1;
        savePhase = "idle";
        saveReady = false;
        saveStatus.textContent = "";
        saveStatus.removeAttribute("data-error");
        saveResult.hidden = true;
        byId("payroll-saved-message").textContent = "";
        savedHistory.removeAttribute("href");
        rowModels = [];
        checkStatus.textContent = "";
        retryChecks.hidden = true;
        review.hidden = true;
        driverRows.replaceChildren();
        otherRows.replaceChildren();
        others.hidden = true;
        others.open = false;
        weekInput.value = "";
        weekInput.setCustomValidity("");
        byId("payroll-week-error").hidden = true;
        byId("payroll-week-range").textContent = "";
        releaseDocument();
        updateControlLocks();
    }

    function stopReading() {
        generation += 1;
        if (controller) controller.abort();
        controller = null;
        setBusy(false);
    }

    function calendarDate(value) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
        const parsed = new Date(`${value}T12:00:00Z`);
        return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value ? parsed : null;
    }

    function validWeekStart() {
        const parsed = calendarDate(weekInput.value);
        return parsed && parsed.getUTCDay() === 6 && weekInput.value >= "0001-01-06" && weekInput.value <= "9999-12-25" ? parsed : null;
    }

    function updateWeek() {
        const parsed = calendarDate(weekInput.value);
        const message = !parsed ? "Choose a week beginning date." : parsed.getUTCDay() !== 6 ? "Choose a Saturday." : !validWeekStart() ? "Choose a week within the supported calendar." : "";
        weekInput.setCustomValidity(message);
        const hint = byId("payroll-week-error");
        hint.textContent = message;
        hint.hidden = !message;
        if (!message) {
            const end = new Date(parsed);
            end.setUTCDate(end.getUTCDate() + 6);
            byId("payroll-week-range").textContent = `${dateFormat.format(parsed)} – ${dateFormat.format(end)}`;
        } else {
            byId("payroll-week-range").textContent = "";
        }
        return !message;
    }

    function updateGroups() {
        const mainCount = driverRows.children.length;
        const otherCount = otherRows.children.length;
        byId("payroll-driver-table-wrap").hidden = mainCount === 0;
        byId("payroll-no-driver-rows").hidden = mainCount !== 0;
        others.hidden = otherCount === 0;
        byId("payroll-other-summary").textContent = `Other employees (${otherCount})`;
        refreshRowChecks();
    }

    function selectedDriverId(model) {
        const value = model.select.value;
        if (!/^\d+$/.test(value)) return null;
        const id = Number(value);
        return Number.isSafeInteger(id) && id > 0 ? id : null;
    }

    function amountInPence(value) {
        // String parsing preserves pennies and rejects exponent/extra-decimal
        // inputs instead of rounding them into a different financial amount.
        if (value.length > 32 || !/^\d+(?:\.\d{1,2})?$/.test(value)) return null;
        const [whole, fraction = ""] = value.split(".");
        return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
    }

    function amountMessage(input) {
        if (!input.value) return "Enter an amount.";
        const pence = amountInPence(input.value);
        if (pence === null) return "Use a positive amount with up to 2 decimals.";
        return pence <= 100n || pence >= 300000n ? "Enter more than £1 and less than £3,000." : "";
    }

    function showFieldMessage(field, message, included) {
        field.input.required = included;
        field.input.disabled = !included || editingLocked();
        field.input.setCustomValidity(message);
        field.input.setAttribute("aria-invalid", String(Boolean(message)));
        field.error.textContent = message;
        field.error.hidden = !message;
    }

    function appendExistingPayslip(container, entry, multiple) {
        const item = document.createElement("div");
        item.className = "payroll-import-existing-item";
        const amounts = document.createElement("span");
        amounts.textContent = `Wage £${entry.total_wage} · cost £${entry.total_cost_to_employer}`;
        const link = document.createElement("a");
        link.textContent = multiple ? `View payslip #${entry.id}` : "View payslip";
        link.href = entry.review_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        item.append(amounts, link);
        container.append(item);
    }

    function safeLocalUrl(value, pattern) {
        if (typeof value !== "string") throw new Error("invalid_response");
        const url = new URL(value, window.location.origin);
        if (url.origin !== window.location.origin || url.search || url.hash || !pattern.test(url.pathname)) throw new Error("invalid_response");
        return url.pathname;
    }

    function appendAction(container, text, url) {
        const link = document.createElement("a");
        link.textContent = text;
        link.href = url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        container.append(link);
    }

    function serverMessage(model, field) {
        return model.serverErrors.find((error) => error.field === field)?.message || "";
    }

    function editDraft(model, field) {
        if (editingLocked()) return false;
        if (model) model.serverErrors = field ? model.serverErrors.filter((error) => error.field !== field) : [];
        else for (const row of rowModels) row.serverErrors = [];
        savePhase = "idle";
        saveStatus.textContent = "";
        saveStatus.removeAttribute("data-error");
        return true;
    }

    function refreshRowChecks() {
        const included = rowModels.filter((model) => model.row.parentElement === driverRows);
        const driverCounts = new Map();
        for (const model of included) {
            const id = selectedDriverId(model);
            if (id !== null) driverCounts.set(id, (driverCounts.get(id) || 0) + 1);
        }
        let attentionCount = 0;
        for (const model of rowModels) {
            const active = model.row.parentElement === driverRows;
            const id = selectedDriverId(model);
            const driverMessage = !active ? "" : id === null ? "Choose a driver or exclude this employee." : driverCounts.get(id) > 1 ? "Driver selected more than once." : serverMessage(model, "driver_id");
            model.select.setCustomValidity(driverMessage);
            model.select.setAttribute("aria-invalid", String(Boolean(driverMessage)));
            model.driverError.textContent = driverMessage;
            model.driverError.hidden = !driverMessage;
            const wageMessage = active ? amountMessage(model.wage.input) || serverMessage(model, "total_wage") : "";
            let costMessage = active ? amountMessage(model.cost.input) || serverMessage(model, "total_cost_to_employer") : "";
            if (active && !wageMessage && !costMessage && amountInPence(model.cost.input.value) < amountInPence(model.wage.input.value)) {
                costMessage = "Employer cost is below total wage.";
            }
            showFieldMessage(model.wage, wageMessage, active);
            showFieldMessage(model.cost, costMessage, active);
            const entries = active && checkPhase === "complete" ? existingByDriver.get(id) || [] : [];
            model.existing.replaceChildren();
            model.existing.hidden = entries.length === 0;
            if (entries.length) {
                const heading = document.createElement("strong");
                heading.textContent = entries.length === 1 ? "Payslip already recorded" : `${entries.length} payslips already recorded`;
                model.existing.append(heading);
                for (const entry of entries) appendExistingPayslip(model.existing, entry, entries.length > 1);
            }
            const day = active && checkPhase === "complete" ? daysByDriver.get(id) : null;
            model.dayCheck.replaceChildren();
            model.dayCheck.hidden = !day || day.status === "ready";
            if (day && day.status !== "ready") {
                const date = dateFormat.format(calendarDate(day.date));
                const message = document.createElement("span");
                message.textContent = day.status === "missing" ? `No day entry for ${date}.` : `Multiple day entries for ${date}.`;
                model.dayCheck.append(message);
                appendAction(model.dayCheck, day.status === "missing" ? "Add day entry" : "Review day entries", day.status === "missing" ? day.add_url : day.add_url.replace(/\/entry$/, "/history"));
            }
            const otherErrors = active ? model.serverErrors.filter((error) => !["driver_id", "total_wage", "total_cost_to_employer"].includes(error.field)) : [];
            model.saveError.replaceChildren();
            model.saveError.hidden = !otherErrors.length;
            for (const error of otherErrors) {
                const message = document.createElement("span");
                message.textContent = error.message;
                model.saveError.append(message);
                if (error.action_url) appendAction(model.saveError, error.field === "existing_payslip" ? "View payslip" : "Review day entries", error.action_url);
            }
            const needsAttention = Boolean(driverMessage || wageMessage || costMessage || entries.length || day && day.status !== "ready" || otherErrors.length);
            model.row.classList.toggle("payroll-import-row-warning", needsAttention);
            if (active && needsAttention) attentionCount += 1;
        }
        const count = included.length;
        byId("payroll-driver-count").textContent = `${count} ${count === 1 ? "entry" : "entries"}${attentionCount ? ` · ${attentionCount} need${attentionCount === 1 ? "s" : ""} attention` : ""}`;
        retryChecks.hidden = review.hidden || savePhase === "complete";
        retryChecks.textContent = checkPhase === "failed" ? "Retry check" : "Recheck entries";
        if (editingLocked()) {
            checkStatus.textContent = "";
        } else if (checkPhase === "pending" || checkPhase === "checking") {
            checkStatus.textContent = "Checking existing payslips and day entries…";
        } else if (checkPhase === "failed") {
            checkStatus.textContent = "Existing payslips and day entries could not be checked.";
        } else if (checkPhase === "invalid") {
            checkStatus.textContent = "Choose a valid payroll week to check existing payslips.";
        } else if (checkPhase === "complete" && count && !attentionCount && validWeekStart()) {
            checkStatus.textContent = "Ready to save the selected payslips.";
        } else {
            checkStatus.textContent = "";
        }
        saveReady = Boolean(count && !attentionCount && validWeekStart() && checkPhase === "complete" && included.every((model) => daysByDriver.get(selectedDriverId(model))?.status === "ready"));
        updateControlLocks();
    }

    function cancelCheckWork() {
        checkGeneration += 1;
        if (checkTimer !== null) window.clearTimeout(checkTimer);
        checkTimer = null;
        if (checkController) checkController.abort();
        checkController = null;
    }

    function checkSnapshot() {
        const start = validWeekStart();
        if (!start) return null;
        const end = new Date(start);
        end.setUTCDate(end.getUTCDate() + 6);
        const driverIds = [...new Set(rowModels.filter((model) => model.row.parentElement === driverRows).map(selectedDriverId).filter((id) => id !== null))].sort((a, b) => a - b);
        return {week_start: weekInput.value, week_end: end.toISOString().slice(0, 10), driver_ids: driverIds};
    }

    function checkedEntries(data, snapshot) {
        if (!data || data.week_start !== snapshot.week_start || data.week_end !== snapshot.week_end || data.entry_date !== snapshot.week_end || !Array.isArray(data.existing_payslips) || !Array.isArray(data.day_entries)) throw new Error("invalid_check_response");
        const expected = new Set(snapshot.driver_ids);
        const result = new Map();
        for (const group of data.existing_payslips) {
            if (!group || !expected.has(group.driver_id) || result.has(group.driver_id) || !Array.isArray(group.payslips)) throw new Error("invalid_check_response");
            for (const entry of group.payslips) {
                if (!entry || !Number.isSafeInteger(entry.id) || entry.id <= 0 || typeof entry.total_wage !== "string" || typeof entry.total_cost_to_employer !== "string" || typeof entry.review_url !== "string") throw new Error("invalid_check_response");
                entry.review_url = safeLocalUrl(entry.review_url, /^\/payslip\/add_payslip\/\d+\/edit$/);
            }
            result.set(group.driver_id, group.payslips);
        }
        if (result.size !== expected.size) throw new Error("invalid_check_response");
        const days = new Map();
        for (const day of data.day_entries) {
            if (!day || !expected.has(day.driver_id) || days.has(day.driver_id) || day.date !== snapshot.week_end || !["ready", "missing", "multiple"].includes(day.status)) throw new Error("invalid_check_response");
            day.add_url = safeLocalUrl(day.add_url, /^\/day\/add_day\/0\/(?:entry|history)$/);
            days.set(day.driver_id, day);
        }
        if (days.size !== expected.size) throw new Error("invalid_check_response");
        return {existing: result, days};
    }

    async function runChecks(snapshot, serial) {
        if (serial !== checkGeneration) return;
        const requestController = new AbortController();
        checkController = requestController;
        checkPhase = "checking";
        refreshRowChecks();
        const timeout = window.setTimeout(() => requestController.abort(), 15_000);
        try {
            const response = await fetch(root.dataset.checkUrl, {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": root.dataset.csrfToken},
                credentials: "same-origin",
                body: JSON.stringify({week_start: snapshot.week_start, driver_ids: snapshot.driver_ids}),
                signal: requestController.signal,
                cache: "no-store",
            });
            const data = await response.json();
            if (serial !== checkGeneration) return;
            if (!response.ok) throw new Error("check_unavailable");
            const checked = checkedEntries(data, snapshot);
            existingByDriver = checked.existing;
            daysByDriver = checked.days;
            // Fresh database evidence replaces only database-related save errors.
            for (const model of rowModels) model.serverErrors = model.serverErrors.filter((error) => !["driver_id", "day", "existing_payslip"].includes(error.field));
            checkPhase = "complete";
        } catch (error) {
            if (serial !== checkGeneration) return;
            existingByDriver = new Map();
            daysByDriver = new Map();
            checkPhase = "failed";
        } finally {
            window.clearTimeout(timeout);
            if (serial === checkGeneration) {
                checkController = null;
                refreshRowChecks();
            }
        }
    }

    function scheduleChecks({immediate = false, force = false} = {}) {
        if (review.hidden || editingLocked()) return;
        const snapshot = checkSnapshot();
        const key = snapshot ? JSON.stringify([snapshot.week_start, snapshot.driver_ids]) : null;
        if (!force && key !== null && key === checkKey && ["pending", "checking", "complete"].includes(checkPhase)) {
            refreshRowChecks();
            return;
        }
        cancelCheckWork();
        checkKey = key;
        existingByDriver = new Map();
        daysByDriver = new Map();
        checkPhase = snapshot ? snapshot.driver_ids.length ? "pending" : "complete" : "invalid";
        refreshRowChecks();
        if (!snapshot || !snapshot.driver_ids.length) return;
        const serial = checkGeneration;
        if (immediate) runChecks(snapshot, serial);
        else checkTimer = window.setTimeout(() => { checkTimer = null; runChecks(snapshot, serial); }, 200);
    }

    function insertBySource(body, row) {
        const after = [...body.children].find((existing) => Number(existing.dataset.sourceIndex) > Number(row.dataset.sourceIndex));
        body.insertBefore(row, after || null);
    }

    function makeRow(source, drivers, duplicatedDriverNames) {
        const row = document.createElement("tr");
        row.dataset.sourceIndex = String(source.source_index);
        const employeeCell = document.createElement("td");
        const name = document.createElement("span");
        name.className = "payroll-import-source-name";
        name.textContent = source.employee_name;
        employeeCell.append(name);
        const page = document.createElement("button");
        page.type = "button";
        page.className = "payroll-import-source";
        page.textContent = `Page ${source.page_number}`;
        page.setAttribute("aria-label", `Show source page for ${source.employee_name}`);
        page.addEventListener("click", () => showPage(source.page_number));
        employeeCell.append(page);
        row.append(employeeCell);

        const driverCell = document.createElement("td");
        const select = document.createElement("select");
        select.className = "browser-default";
        select.setAttribute("aria-label", `Driver for ${source.employee_name}`);
        if (source.match_status === "ambiguous") {
            const chooseOption = document.createElement("option");
            chooseOption.value = "__choose__";
            chooseOption.textContent = "Choose driver";
            chooseOption.disabled = true;
            select.append(chooseOption);
        }
        const excludedOption = document.createElement("option");
        excludedOption.value = "";
        excludedOption.textContent = "Exclude";
        select.append(excludedOption);
        for (const driver of drivers) {
            const option = document.createElement("option");
            option.value = String(driver.id);
            const ambiguousCandidate = source.match_status === "ambiguous" &&
                Array.isArray(source.candidate_driver_ids) &&
                source.candidate_driver_ids.some((id) => String(id) === String(driver.id));
            option.textContent = ambiguousCandidate || duplicatedDriverNames.has(driver.name.toLocaleLowerCase()) ? `${driver.name} (ID ${driver.id})` : driver.name;
            select.append(option);
        }
        select.value = source.driver_id == null ? source.match_status === "ambiguous" ? "__choose__" : "" : String(source.driver_id);
        const note = document.createElement("span");
        note.className = "payroll-import-field-error";
        note.id = `payroll-${source.source_index}-driver-error`;
        note.hidden = true;
        select.setAttribute("aria-describedby", note.id);
        const existing = document.createElement("div");
        existing.className = "payroll-import-existing";
        existing.hidden = true;
        const dayCheck = document.createElement("div");
        dayCheck.className = "payroll-import-day-check";
        dayCheck.hidden = true;
        const saveError = document.createElement("div");
        saveError.className = "payroll-import-save-row-error";
        saveError.hidden = true;
        select.addEventListener("change", () => {
            if (!editDraft(model)) return;
            const target = select.value ? driverRows : otherRows;
            if (row.parentElement !== target) {
                if (target === otherRows) others.open = true;
                insertBySource(target, row);
                updateGroups();
                select.focus({preventScroll: true});
            }
            scheduleChecks();
        });
        driverCell.append(select, note, existing, dayCheck, saveError);
        row.append(driverCell);

        const model = {row, select, driverError: note, existing, dayCheck, saveError, serverErrors: []};
        for (const [field, label] of [["total_wage", "Total wage"], ["total_cost_to_employer", "Employer cost"]]) {
            const cell = document.createElement("td");
            const input = document.createElement("input");
            input.type = "number";
            input.step = "0.01";
            input.required = true;
            input.inputMode = "decimal";
            input.value = source[field];
            input.setAttribute("aria-label", `${label} for ${source.employee_name}`);
            input.addEventListener("wheel", (event) => event.preventDefault(), {passive: false});
            const changed = () => { if (editDraft(model, field)) refreshRowChecks(); };
            input.addEventListener("input", changed);
            input.addEventListener("change", changed);
            const error = document.createElement("span");
            error.className = "payroll-import-field-error";
            error.id = `payroll-${source.source_index}-${field}-error`;
            error.hidden = true;
            input.setAttribute("aria-describedby", error.id);
            cell.append(input, error);
            row.append(cell);
            model[field === "total_wage" ? "wage" : "cost"] = {input, error};
        }
        rowModels.push(model);
        return row;
    }

    function renderReport(data, file) {
        if (!data || !data.report || !Array.isArray(data.rows) || !Array.isArray(data.drivers)) {
            throw new Error("invalid_response");
        }
        resetPreview();
        documentUrl = createDocumentUrl(file);
        const nameCounts = new Map();
        for (const driver of data.drivers) {
            const key = driver.name.toLocaleLowerCase();
            nameCounts.set(key, (nameCounts.get(key) || 0) + 1);
        }
        const duplicatedNames = new Set([...nameCounts].filter(([, count]) => count > 1).map(([name]) => name));
        for (const source of data.rows) {
            const row = makeRow(source, data.drivers, duplicatedNames);
            (source.match_status === "unmatched" ? otherRows : driverRows).append(row);
        }
        weekInput.value = data.report.week_start;
        updateWeek();
        const payDate = calendarDate(data.report.pay_date);
        byId("payroll-report-date").textContent = payDate ? `Report pay date: ${dateFormat.format(payDate)}` : "";
        byId("payroll-document-name").textContent = file.name;
        const firstRelevant = data.rows.find((source) => source.match_status !== "unmatched") || data.rows[0];
        showPage(firstRelevant ? firstRelevant.page_number : 1);
        review.hidden = false;
        updateGroups();
        scheduleChecks({immediate: true});
    }

    fileInput.addEventListener("change", () => {
        if (savePhase === "saving") return;
        const file = fileInput.files && fileInput.files[0];
        // Cancelling a chooser must not erase the existing editable preview.
        if (!file) return;
        stopReading();
        resetPreview();
        clearError();
        status.textContent = "";
        chosenFile = null;
        clearButton.hidden = false;
        if (!/\.pdf$/i.test(file.name)) {
            showError("Choose a PDF management report.");
        } else if (file.size > maxBytes) {
            showError("The PDF is too large. Use a report under 10 MB.");
        } else if (file.size === 0) {
            showError("The PDF is empty. Choose a weekly management report.");
        } else {
            chosenFile = file;
        }
        setBusy(false);
    });

    clearButton.addEventListener("click", () => {
        if (savePhase === "saving") return;
        stopReading();
        resetPreview();
        clearError();
        status.textContent = "";
        chosenFile = null;
        fileInput.value = "";
        clearButton.hidden = true;
        setBusy(false);
    });

    readButton.addEventListener("click", async () => {
        if (busy || editingLocked() || !chosenFile) return;
        const file = chosenFile;
        const current = ++generation;
        const requestController = new AbortController();
        controller = requestController;
        resetPreview();
        clearError();
        setBusy(true);
        status.textContent = "Reading PDF…";
        let timedOut = false;
        const timer = window.setTimeout(() => { timedOut = true; requestController.abort(); }, 30_000);
        try {
            const response = await fetch(root.dataset.readUrl, {
                method: "POST",
                headers: {"Content-Type": "application/pdf", "X-CSRFToken": root.dataset.csrfToken},
                credentials: "same-origin",
                body: file,
                signal: requestController.signal,
                cache: "no-store",
            });
            const data = await response.json();
            if (current !== generation) return;
            if (!response.ok) {
                const message = data && data.error && typeof data.error.message === "string" ? data.error.message : "The PDF could not be read. Please try again.";
                showError(message);
                return;
            }
            renderReport(data, file);
        } catch (error) {
            if (current !== generation) return;
            resetPreview();
            showError(timedOut ? "Reading took too long. Please try again." : "The PDF could not be read. Please try again.");
        } finally {
            window.clearTimeout(timer);
            if (current === generation) {
                controller = null;
                status.textContent = "";
                setBusy(false);
            }
        }
    });

    function saveRows() {
        return rowModels.filter((model) => model.row.parentElement === driverRows).map((model) => ({
            source_index: Number(model.row.dataset.sourceIndex),
            driver_id: selectedDriverId(model),
            total_wage: model.wage.input.value,
            total_cost_to_employer: model.cost.input.value,
        }));
    }

    function applySaveErrors(data) {
        if (!data || !Array.isArray(data.row_errors)) return;
        const fields = new Set(["driver_id", "total_wage", "total_cost_to_employer", "day", "existing_payslip"]);
        for (const error of data.row_errors) {
            if (!error || !fields.has(error.field) || typeof error.message !== "string") continue;
            const model = rowModels.find((row) => Number(row.row.dataset.sourceIndex) === error.source_index && selectedDriverId(row) === error.driver_id);
            if (!model) continue;
            const message = {field: error.field, message: error.message};
            if (error.action_url) {
                try {
                    const pattern = error.field === "existing_payslip" ? /^\/payslip\/add_payslip\/\d+\/edit$/ : /^\/day\/add_day\/0\/(?:entry|history)$/;
                    message.action_url = safeLocalUrl(error.action_url, pattern);
                }
                catch (invalidUrl) { /* The fixed row message remains useful. */ }
            }
            model.serverErrors.push(message);
        }
    }

    function confirmSaved(data, payload, snapshot) {
        if (!data || data.saved_count !== payload.rows.length || data.week_start !== snapshot.week_start || data.week_end !== snapshot.week_end || data.entry_date !== snapshot.week_end || !Array.isArray(data.payslips) || data.payslips.length !== payload.rows.length) throw new Error("unconfirmed_save");
        const seen = new Set();
        const savedIds = new Set();
        for (const entry of data.payslips) {
            if (!entry || !Number.isSafeInteger(entry.id) || entry.id <= 0 || seen.has(entry.source_index) || savedIds.has(entry.id) || !payload.rows.some((row) => row.source_index === entry.source_index && row.driver_id === entry.driver_id)) throw new Error("unconfirmed_save");
            safeLocalUrl(entry.review_url, /^\/payslip\/add_payslip\/\d+\/edit$/);
            seen.add(entry.source_index);
            savedIds.add(entry.id);
        }
        return safeLocalUrl(data.history_url, /^\/payslip\/add_payslip\/0\/history$/);
    }

    saveButton.addEventListener("click", async () => {
        if (editingLocked()) return;
        refreshRowChecks();
        if (!saveReady) return;
        const snapshot = checkSnapshot();
        const payload = {week_start: snapshot.week_start, rows: saveRows()};
        const serial = ++saveGeneration;
        const requestController = new AbortController();
        cancelCheckWork();
        for (const model of rowModels) model.serverErrors = [];
        savePhase = "saving";
        saveStatus.textContent = "Saving the selected payslips…";
        saveStatus.removeAttribute("data-error");
        refreshRowChecks();
        // A lost response does not prove whether the transaction committed.
        // Never retry a mutation automatically; recheck recorded entries first.
        const timeout = window.setTimeout(() => requestController.abort(), 30_000);
        try {
            const response = await fetch(root.dataset.saveUrl, {
                method: "POST",
                headers: {"Content-Type": "application/json", "X-CSRFToken": root.dataset.csrfToken},
                credentials: "same-origin",
                body: JSON.stringify(payload),
                signal: requestController.signal,
                cache: "no-store",
            });
            const data = await response.json();
            if (serial !== saveGeneration) return;
            if (!response.ok) {
                savePhase = "failed";
                applySaveErrors(data);
                saveStatus.textContent = data && data.error && typeof data.error.message === "string" ? data.error.message : "The save could not be confirmed. Check recorded payslips before trying again.";
                saveStatus.setAttribute("data-error", "true");
            } else {
                const historyUrl = confirmSaved(data, payload, snapshot);
                savePhase = "complete";
                saveStatus.textContent = "";
                saveStatus.removeAttribute("data-error");
                byId("payroll-saved-message").textContent = `${data.saved_count} ${data.saved_count === 1 ? "payslip" : "payslips"} saved for the week ending ${dateFormat.format(calendarDate(data.entry_date))}.`;
                savedHistory.href = historyUrl;
                saveResult.hidden = false;
            }
        } catch (error) {
            if (serial !== saveGeneration) return;
            savePhase = "failed";
            saveStatus.textContent = "The save could not be confirmed. Check recorded payslips before trying again.";
            saveStatus.setAttribute("data-error", "true");
        } finally {
            window.clearTimeout(timeout);
            if (serial === saveGeneration) {
                refreshRowChecks();
                if (savePhase !== "complete") scheduleChecks({immediate: true, force: true});
            }
        }
    });

    function weekChanged() {
        if (!editDraft()) return;
        updateWeek();
        scheduleChecks();
    }
    weekInput.addEventListener("input", weekChanged);
    weekInput.addEventListener("change", weekChanged);
    retryChecks.addEventListener("click", () => scheduleChecks({immediate: true, force: true}));
    window.addEventListener("pagehide", () => {
        stopReading();
        cancelCheckWork();
        existingByDriver = new Map();
        daysByDriver = new Map();
        checkPhase = "idle";
        releaseDocument();
    });
    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            setBusy(false);
            status.textContent = "";
            if (chosenFile && !review.hidden) {
                documentUrl = createDocumentUrl(chosenFile);
                showPage(visiblePage);
                if (!editingLocked()) scheduleChecks({immediate: true, force: true});
            }
        }
    });
})();
