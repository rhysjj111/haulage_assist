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
    const maxBytes = 10 * 1024 * 1024;
    const dateFormat = new Intl.DateTimeFormat("en-GB", {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
    let chosenFile = null;
    let documentUrl = null;
    let controller = null;
    let generation = 0;
    let busy = false;
    let visiblePage = 1;

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

    function updateWeek() {
        const parsed = calendarDate(weekInput.value);
        const message = !parsed ? "Choose a week beginning date." : parsed.getUTCDay() !== 6 ? "Choose a Saturday." : "";
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
    }

    function updateGroups() {
        const mainCount = driverRows.children.length;
        const otherCount = otherRows.children.length;
        byId("payroll-driver-count").textContent = `${mainCount} ${mainCount === 1 ? "driver entry" : "driver entries"} to review`;
        byId("payroll-driver-table-wrap").hidden = mainCount === 0;
        byId("payroll-no-driver-rows").hidden = mainCount !== 0;
        others.hidden = otherCount === 0;
        byId("payroll-other-summary").textContent = `Other employees (${otherCount})`;
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
        const excludedOption = document.createElement("option");
        excludedOption.value = "";
        excludedOption.textContent = source.match_status === "ambiguous" ? "Choose driver / exclude" : "Exclude";
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
        select.value = source.driver_id == null ? "" : String(source.driver_id);
        const note = document.createElement("span");
        note.className = "payroll-import-match-note";
        note.textContent = source.match_status === "ambiguous" ? "More than one driver matches." : "";
        note.hidden = !note.textContent;
        select.addEventListener("change", () => {
            note.hidden = true;
            const target = select.value ? driverRows : otherRows;
            if (row.parentElement !== target) {
                if (target === otherRows) others.open = true;
                insertBySource(target, row);
                updateGroups();
                select.focus({preventScroll: true});
            }
        });
        driverCell.append(select, note);
        row.append(driverCell);

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
            cell.append(input);
            row.append(cell);
        }
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
        updateGroups();
        review.hidden = false;
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

    weekInput.addEventListener("input", updateWeek);
    weekInput.addEventListener("change", updateWeek);
    window.addEventListener("pagehide", () => { stopReading(); releaseDocument(); });
    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            setBusy(false);
            status.textContent = "";
            if (chosenFile && !review.hidden) {
                documentUrl = createDocumentUrl(chosenFile);
                showPage(visiblePage);
            }
        }
    });
})();
