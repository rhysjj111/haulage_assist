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

    function setBusy(value) {
        busy = value;
        readButton.disabled = value || !chosenFile;
        readButton.textContent = value ? "Reading…" : "Read PDF";
        root.setAttribute("aria-busy", String(value));
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
        field.input.disabled = !included;
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
            const driverMessage = !active ? "" : id === null ? "Choose a driver or exclude this employee." : driverCounts.get(id) > 1 ? "Driver selected more than once." : "";
            model.select.setCustomValidity(driverMessage);
            model.select.setAttribute("aria-invalid", String(Boolean(driverMessage)));
            model.driverError.textContent = driverMessage;
            model.driverError.hidden = !driverMessage;
            const wageMessage = active ? amountMessage(model.wage.input) : "";
            let costMessage = active ? amountMessage(model.cost.input) : "";
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
            const needsAttention = Boolean(driverMessage || wageMessage || costMessage || entries.length);
            model.row.classList.toggle("payroll-import-row-warning", needsAttention);
            if (active && needsAttention) attentionCount += 1;
        }
        const count = included.length;
        byId("payroll-driver-count").textContent = `${count} ${count === 1 ? "entry" : "entries"}${attentionCount ? ` · ${attentionCount} need${attentionCount === 1 ? "s" : ""} attention` : ""}`;
        retryChecks.hidden = checkPhase !== "failed";
        if (checkPhase === "pending" || checkPhase === "checking") {
            checkStatus.textContent = "Checking existing payslips…";
        } else if (checkPhase === "failed") {
            checkStatus.textContent = "Existing payslips could not be checked.";
        } else if (checkPhase === "invalid") {
            checkStatus.textContent = "Choose a valid payroll week to check existing payslips.";
        } else if (checkPhase === "complete" && count && !attentionCount && validWeekStart()) {
            checkStatus.textContent = "No issues found in these checks.";
        } else {
            checkStatus.textContent = "";
        }
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
        if (!data || data.week_start !== snapshot.week_start || data.week_end !== snapshot.week_end || !Array.isArray(data.existing_payslips)) throw new Error("invalid_check_response");
        const expected = new Set(snapshot.driver_ids);
        const result = new Map();
        for (const group of data.existing_payslips) {
            if (!group || !expected.has(group.driver_id) || result.has(group.driver_id) || !Array.isArray(group.payslips)) throw new Error("invalid_check_response");
            for (const entry of group.payslips) {
                if (!entry || !Number.isSafeInteger(entry.id) || entry.id <= 0 || typeof entry.total_wage !== "string" || typeof entry.total_cost_to_employer !== "string" || typeof entry.review_url !== "string") throw new Error("invalid_check_response");
                const url = new URL(entry.review_url, window.location.origin);
                if (url.origin !== window.location.origin || !/^\/payslip\/add_payslip\/\d+\/edit$/.test(url.pathname)) throw new Error("invalid_check_response");
            }
            result.set(group.driver_id, group.payslips);
        }
        if (result.size !== expected.size) throw new Error("invalid_check_response");
        return result;
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
            existingByDriver = checkedEntries(data, snapshot);
            checkPhase = "complete";
        } catch (error) {
            if (serial !== checkGeneration) return;
            existingByDriver = new Map();
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
        if (review.hidden) return;
        const snapshot = checkSnapshot();
        const key = snapshot ? JSON.stringify([snapshot.week_start, snapshot.driver_ids]) : null;
        if (!force && key !== null && key === checkKey && ["pending", "checking", "complete"].includes(checkPhase)) {
            refreshRowChecks();
            return;
        }
        cancelCheckWork();
        checkKey = key;
        existingByDriver = new Map();
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
        select.addEventListener("change", () => {
            const target = select.value ? driverRows : otherRows;
            if (row.parentElement !== target) {
                if (target === otherRows) others.open = true;
                insertBySource(target, row);
                updateGroups();
                select.focus({preventScroll: true});
            }
            scheduleChecks();
        });
        driverCell.append(select, note, existing);
        row.append(driverCell);

        const model = {row, select, driverError: note, existing};
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
            input.addEventListener("input", refreshRowChecks);
            input.addEventListener("change", refreshRowChecks);
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
        if (busy || !chosenFile) return;
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

    function weekChanged() {
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
                scheduleChecks({immediate: true, force: true});
            }
        }
    });
})();
