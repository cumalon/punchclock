const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
const isSupervisor = document.querySelector('meta[name="user-role"]').content === "supervisor";

function adminHeaders(headers = {}) {
    return {...headers, "X-CSRF-Token": csrfToken};
}

const employees = document.getElementById("employees");
const form = document.getElementById("new-employee");
const formMessage = document.getElementById("form-message");
let adminEmployees = [];
let punchLoadGeneration = 0;

async function loadEmployees() {
    const response = await fetch("/api/admin/employees");
    const data = await response.json();
    employees.replaceChildren();

    adminEmployees = data.employees;

    for (const employee of data.employees) {
        const row = document.createElement("div");
        row.className = "employee";

        const name = document.createElement("input");
        name.value = employee.name;

        const pin = document.createElement("input");
        pin.type = "password";
        pin.inputMode = "numeric";
        pin.placeholder = "Nou PIN";
        pin.maxLength = 8;

        const activeLabel = document.createElement("label");
        const active = document.createElement("input");
        active.type = "checkbox";
        active.checked = Boolean(employee.active);
        activeLabel.append(active, " Actiu");

        const save = document.createElement("button");
        save.type = "button";
        save.textContent = "Desar";

        const message = document.createElement("span");
        message.className = "message";

        save.addEventListener("click", async () => {
            save.disabled = true;
            const payload = {name: name.value, active: active.checked};
            if (pin.value.trim()) payload.pin = pin.value.trim();

            try {
                const response = await fetch("/api/admin/employees/" + employee.id, {
                    method: "PATCH",
                    headers: adminHeaders({"Content-Type": "application/json"}),
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                message.textContent = data.ok ? "Desat" : data.error;
                if (data.ok) pin.value = "";
            } catch {
                message.textContent = "Error de connexió";
            } finally {
                save.disabled = false;
            }
        });

        row.append(name, pin, activeLabel, save, message);
        employees.appendChild(row);
    }
}

form.addEventListener("submit", async event => {
    event.preventDefault();
    formMessage.textContent = "";

    try {
        const response = await fetch("/api/admin/employees", {
            method: "POST",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({
                name: document.getElementById("new-name").value,
                pin: document.getElementById("new-pin").value
            })
        });
        const data = await response.json();

        if (!data.ok) {
            formMessage.textContent = data.error;
            return;
        }

        form.reset();
        formMessage.textContent = "Empleat creat";
        await loadEmployees();
    } catch {
        formMessage.textContent = "Error de connexió";
    }
});

if (!isSupervisor) {
    loadEmployees().catch(() => {
        employees.textContent = "No s'han pogut carregar els empleats";
    });
}


const employeesSection = document.getElementById("employees-section");
const punchesSection = document.getElementById("punches-section");
const hoursReportSection = document.getElementById("hours-report-section");
const settingsSection = document.getElementById("settings-section");
const backupsSection = document.getElementById("backups-section");
const punchEmployee = document.getElementById("punch-employee");
const punchesBody = document.getElementById("punches");
const punchEditor = document.getElementById("punch-editor");
const editPunchEmployee = document.getElementById("edit-punch-employee");
const incidentReviewEditor = document.getElementById("incident-review-editor");
let currentPunch = null;
let currentIncidentPunch = null;

const actionIcons = {
    edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l11-11-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/></svg>',
    review: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12.5 9 17l11-11"/><path d="M4 5h6M4 9h4"/></svg>',
    reopen: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8v5h5"/><path d="M5.5 12a7 7 0 1 0 2-5"/></svg>',
    save: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4h12l2 2v14H5Z"/><path d="M8 4v6h8V4M8 20v-6h8v6"/></svg>',
    restore: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8v5h5"/><path d="M5.5 12a7 7 0 1 0 2-5"/><path d="M12 8v4l3 2"/></svg>'
};

function setActionButton(button, icon, label) {
    button.classList.add("action-button", "icon-action");
    button.innerHTML = actionIcons[icon];
    button.setAttribute("aria-label", label);
    button.dataset.tooltip = label;
}

function showSection(section) {
    if (isSupervisor && !["punches", "leaves", "hours-report"].includes(section)) section = "punches";
    employeesSection.classList.toggle("hidden", section !== "employees");
    punchesSection.classList.toggle("hidden", section !== "punches");
    hoursReportSection.classList.toggle("hidden", section !== "hours-report");
    document.getElementById("leaves-section").classList.toggle("hidden", section !== "leaves");
    document.getElementById("leave-supervision-detail").classList.add("hidden");
    settingsSection.classList.toggle("hidden", section !== "settings");
    backupsSection.classList.toggle("hidden", section !== "backups");
    const leaveTypesSection = document.getElementById("leave-types-section");
    if (leaveTypesSection) leaveTypesSection.classList.toggle("hidden", section !== "leave-types");
    const usersSection = document.getElementById("users-section");
    if (usersSection) usersSection.classList.toggle("hidden", section !== "users");

    document.querySelectorAll("[data-section]").forEach(link => {
        link.classList.toggle("active", link.dataset.section === section);
    });

    document.querySelector(".page-header").classList.toggle("hidden", section !== "employees");

    if (section === "punches") loadPunches();
    if (section === "hours-report") loadHoursReport();
    if (section === "leaves") loadSupervisionLeaves();
    if (section === "settings") loadSettings();
    if (section === "users") loadWebUsers();
    if (section === "leave-types") loadLeaveTypes();
    if (section === "backups") {
        loadBackups();
        startBackupUsbPolling();
    } else {
        stopBackupUsbPolling();
    }
}

async function loadPunchFilters() {
    const response = await fetch("/api/admin/employees");
    const data = await response.json();

    const terminalOption = document.createElement("option");
    terminalOption.value = "terminal";
    terminalOption.textContent = "Terminal";
    punchEmployee.appendChild(terminalOption);

    for (const employee of data.employees) {
        const option = document.createElement("option");
        option.value = employee.id;
        option.textContent = employee.name;
        punchEmployee.appendChild(option);
    }
}

async function loadPunches() {
    const generation = ++punchLoadGeneration;
    const params = new URLSearchParams();
    if (punchEmployee.value) params.set("employee_id", punchEmployee.value);

    const dateFrom = document.getElementById("date-from").value;
    const dateTo = document.getElementById("date-to").value;
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);

    const response = await fetch("/api/admin/timeline?" + params.toString());
    const data = await response.json();
    if (generation !== punchLoadGeneration) return;
    punchesBody.replaceChildren();

    for (const punch of data.items) {
        const date = new Date(punch.timestamp);
        const row = document.createElement("tr");
        const technical = punch.kind === "terminal_event";
        if (technical) row.className = "technical-event";
        const values = [
            date.toLocaleDateString("ca-ES"),
            date.toLocaleTimeString("ca-ES", {hour: "2-digit", minute: "2-digit", second: "2-digit"}),
            technical ? "⚙ Terminal" : punch.employee_name,
            technical ? (punch.type === "startup" ? "Arrencada" : punch.type) : (punch.type === "entrada" ? "Entrada" : "Sortida"),
            technical ? "—" : punch.method,
            technical ? punch.detail : (punch.incident
                ? (punch.incident_reviewed ? "✓ Revisada · " : "⚠ Pendent · ") + punch.note
                : "")
        ];
        values.forEach((value, index) => {
            const cell = document.createElement("td");
            cell.textContent = value;
            if (!technical && punch.incident && index === 5) {
                cell.classList.add("incident-status", punch.incident_reviewed ? "incident-reviewed" : "incident-pending");
            }
            row.appendChild(cell);
        });
        if (!technical) {
            const actionCell = document.createElement("td");
            actionCell.className = "row-actions";
            const actionGroup = document.createElement("div");
            actionGroup.className = "action-group";
            const edit = document.createElement("button");
            edit.type = "button";
            setActionButton(edit, "edit", "Corregir");
            edit.addEventListener("click", () => openPunchEditor(punch));
            actionGroup.appendChild(edit);
            if (punch.incident) {
                const review = document.createElement("button");
                review.type = "button";
                setActionButton(
                    review,
                    punch.incident_reviewed ? "reopen" : "review",
                    punch.incident_reviewed ? "Reobrir incidència" : "Revisar incidència"
                );
                review.addEventListener("click", () => openIncidentReview(punch));
                actionGroup.appendChild(review);
            }
            actionCell.appendChild(actionGroup);
            row.appendChild(actionCell);
        } else {
            const actionCell = document.createElement("td");
            actionCell.className = "row-actions row-actions-empty";
            row.appendChild(actionCell);
        }
        punchesBody.appendChild(row);
    }

    if (!data.items.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 7;
        cell.textContent = "No hi ha fitxatges per als filtres seleccionats.";
        row.appendChild(cell);
        punchesBody.appendChild(row);
    }
}

const sectionByHash = {
    "#fitxatges": "punches",
    "#permisos-personal": "leaves",
    "#comput-hores": "hours-report",
    "#treballadors": "employees",
    "#usuaris": "users",
    "#permisos": "leave-types",
    "#copies": "backups",
    "#configuracio": "settings"
};

function showSectionFromHash() {
    showSection(sectionByHash[location.hash] || (isSupervisor ? "punches" : "employees"));
}

document.querySelectorAll("[data-section]").forEach(link => {
    link.addEventListener("click", () => {
        // The href updates the hash; hashchange renders the matching section.
    });
});

window.addEventListener("hashchange", showSectionFromHash);

for (const filterId of ["punch-employee", "date-from", "date-to"]) {
    document.getElementById(filterId).addEventListener("change", loadPunches);
}

loadPunchFilters();


function reportDuration(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(total / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const remainingSeconds = total % 60;
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(remainingSeconds).padStart(2, "0")}`;
}

function hoursReportParams() {
    const params = new URLSearchParams();
    const employeeId = document.getElementById("hours-report-employee").value;
    const dateFrom = document.getElementById("hours-report-from").value;
    const dateTo = document.getElementById("hours-report-to").value;
    if (employeeId) params.set("employee_id", employeeId);
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    return params;
}

async function loadHoursReportFilters() {
    const response = await fetch("/api/admin/employees");
    const data = await response.json();
    const select = document.getElementById("hours-report-employee");
    for (const employee of data.employees) {
        const option = document.createElement("option");
        option.value = employee.id;
        option.textContent = employee.name;
        select.appendChild(option);
    }
    const now = new Date();
    const localDate = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    document.getElementById("hours-report-from").value =
        `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
    document.getElementById("hours-report-to").value = localDate;
    if (location.hash === "#comput-hores") loadHoursReport();
}

function appendReportCell(row, text) {
    const cell = document.createElement("td");
    cell.textContent = text;
    row.appendChild(cell);
}

async function loadHoursReport() {
    const message = document.getElementById("hours-report-message");
    const params = hoursReportParams();
    const summaryBody = document.getElementById("hours-report-summary");
    const daysBody = document.getElementById("hours-report-days");
    const incidentsBody = document.getElementById("hours-report-incidents");
    if (!params.get("date_from") || !params.get("date_to")) {
        message.textContent = "Selecciona les dues dates per generar el còmput.";
        return;
    }
    message.textContent = "Calculant...";
    try {
        const response = await fetch("/api/admin/hours-report?" + params.toString());
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "No s'ha pogut generar l'informe");
        summaryBody.replaceChildren();
        daysBody.replaceChildren();
        incidentsBody.replaceChildren();
        for (const employee of data.report.employees) {
            const row = document.createElement("tr");
            appendReportCell(row, employee.employee_name);
            appendReportCell(row, reportDuration(employee.worked_seconds));
            appendReportCell(row, reportDuration(employee.leave_seconds));
            appendReportCell(row, reportDuration(employee.total_seconds));
            appendReportCell(row, String(employee.incident_count));
            summaryBody.appendChild(row);
        }
        for (const day of data.report.days) {
            const row = document.createElement("tr");
            appendReportCell(row, day.date);
            appendReportCell(row, day.employee_name);
            appendReportCell(row, reportDuration(day.worked_seconds));
            appendReportCell(row, reportDuration(day.leave_seconds));
            appendReportCell(row, reportDuration(day.total_seconds));
            appendReportCell(row, day.leave_details.map(item =>
                `${item.leave_type}: ${reportDuration(item.recognized_seconds)} (${item.status}, ${item.record_count})`
            ).join("; "));
            daysBody.appendChild(row);
        }
        for (const issue of data.report.incidents) {
            const row = document.createElement("tr");
            appendReportCell(row, issue.date || "—");
            appendReportCell(row, issue.employee_name);
            appendReportCell(row, issue.category);
            appendReportCell(row, issue.description);
            incidentsBody.appendChild(row);
        }
        message.textContent = `Informe generat: ${data.report.days.length} dies amb dades o incidències.`;
    } catch (error) {
        message.textContent = error.message;
    }
}

document.getElementById("hours-report-run").addEventListener("click", loadHoursReport);
for (const id of ["hours-report-employee", "hours-report-from", "hours-report-to"]) {
    document.getElementById(id).addEventListener("change", loadHoursReport);
}
document.getElementById("hours-report-xlsx").addEventListener("click", () => {
    const params = hoursReportParams();
    window.location.href = "/api/admin/hours-report.xlsx?" + params.toString();
});
loadHoursReportFilters();


document.getElementById("export-csv").addEventListener("click", () => {
    const params = new URLSearchParams();
    if (punchEmployee.value && punchEmployee.value !== "terminal") {
        params.set("employee_id", punchEmployee.value);
    }

    const dateFrom = document.getElementById("date-from").value;
    const dateTo = document.getElementById("date-to").value;
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);

    window.location.href = "/api/admin/export.csv?" + params.toString();
});



async function loadSettings() {
    const response = await fetch("/api/admin/settings");
    const data = await response.json();

    document.getElementById("terminal-name").value = data.settings.terminal_name;
    document.getElementById("terminal-id").value = data.settings.terminal_id;
    document.getElementById("sound-volume").value = data.settings.sound_volume;
    document.getElementById("sound-volume-value").textContent = data.settings.sound_volume + "%";
    document.getElementById("system-version").textContent = data.system.version;
    document.getElementById("system-timezone").textContent = data.system.timezone;
    document.getElementById("system-time").textContent = new Date(data.system.time).toLocaleString("ca-ES");
    document.getElementById("system-database").textContent = data.system.database;
}

document.getElementById("save-settings").addEventListener("click", async () => {
    const message = document.getElementById("settings-message");
    message.textContent = "";

    try {
        const response = await fetch("/api/admin/settings", {
            method: "PUT",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({
                terminal_name: document.getElementById("terminal-name").value,
                terminal_id: document.getElementById("terminal-id").value,
                sound_volume: Number(document.getElementById("sound-volume").value)
            })
        });
        const data = await response.json();
        message.textContent = data.ok ? "Configuració desada" : data.error;
    } catch {
        message.textContent = "Error de connexió";
    }
});

document.getElementById("change-admin-password").addEventListener("click", async () => {
    const message = document.getElementById("admin-password-message");
    const currentPassword = document.getElementById("current-admin-password");
    const newPassword = document.getElementById("new-admin-password");
    const confirmation = document.getElementById("confirm-admin-password");
    message.textContent = "";

    if (newPassword.value.length < 12) {
        message.textContent = "La nova contrasenya ha de tenir com a mínim 12 caràcters.";
        return;
    }
    if (newPassword.value !== confirmation.value) {
        message.textContent = "Les contrasenyes no coincideixen.";
        return;
    }

    try {
        const response = await fetch("/api/admin/change-password", {
            method: "POST",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({
                current_password: currentPassword.value,
                new_password: newPassword.value,
                confirmation: confirmation.value
            })
        });
        const data = await response.json();
        if (!data.ok) {
            message.textContent = data.error;
            return;
        }
        window.location.href = "/admin/login";
    } catch {
        message.textContent = "Error de connexió";
    }
});


document.getElementById("change-admin-pin").addEventListener("click", async () => {
    const message = document.getElementById("admin-pin-message");
    const newPin = document.getElementById("new-admin-pin");
    const confirmation = document.getElementById("confirm-admin-pin");
    message.textContent = "";

    if (!/^\d{6}$/.test(newPin.value)) {
        message.textContent = "El PIN ha de tenir exactament 6 dígits.";
        return;
    }
    if (newPin.value !== confirmation.value) {
        message.textContent = "Els PIN no coincideixen.";
        return;
    }

    try {
        const response = await fetch("/api/admin/change-pin", {
            method: "POST",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({
                new_pin: newPin.value,
                confirmation: confirmation.value
            })
        });
        const data = await response.json();
        message.textContent = data.ok ? "PIN desat" : data.error;
        if (data.ok) {
            newPin.value = "";
            confirmation.value = "";
        }
    } catch {
        message.textContent = "Error de connexió";
    }
});


document.getElementById("sound-volume").addEventListener("input", event => {
    document.getElementById("sound-volume-value").textContent = event.target.value + "%";
});

document.getElementById("export-events-csv").addEventListener("click", () => {
    const params = new URLSearchParams();
    const dateFrom = document.getElementById("date-from").value;
    const dateTo = document.getElementById("date-to").value;
    if (dateFrom) params.set("date_from", dateFrom);
    if (dateTo) params.set("date_to", dateTo);
    window.location.href = "/api/admin/terminal-events.csv?" + params.toString();
});



document.getElementById("logout-button").addEventListener("click", async () => {
    try {
        const response = await fetch("/api/admin/logout", {method: "POST", headers: adminHeaders()});
        if (response.ok) {
            window.location.href = "/admin/login";
        }
    } catch {
        // Keep the current page if the backend cannot be reached.
    }
});


function localDateTimeValue(timestamp) {
    const date = new Date(timestamp);
    const pad = value => String(value).padStart(2, "0");
    return [
        date.getFullYear(), "-", pad(date.getMonth() + 1), "-", pad(date.getDate()),
        "T", pad(date.getHours()), ":", pad(date.getMinutes()), ":", pad(date.getSeconds())
    ].join("");
}

async function openPunchEditor(punch) {
    currentPunch = punch;
    punchEditor.classList.remove("hidden");
    editPunchEmployee.replaceChildren();
    for (const employee of adminEmployees) {
        const option = document.createElement("option");
        option.value = employee.id;
        option.textContent = employee.name;
        option.selected = employee.id === punch.employee_id;
        editPunchEmployee.appendChild(option);
    }
    document.getElementById("edit-punch-timestamp").value = localDateTimeValue(punch.timestamp);
    document.getElementById("edit-punch-type").value = punch.type;
    document.getElementById("edit-punch-reason").value = "";
    document.getElementById("punch-editor-original").textContent =
        "Original seleccionat: " + punch.employee_name + " · " +
        new Date(punch.timestamp).toLocaleString("ca-ES") + " · " +
        (punch.type === "entrada" ? "Entrada" : "Sortida");
    document.getElementById("punch-correction-message").textContent = "";
    await loadCorrectionHistory(punch.id);
    punchEditor.scrollIntoView({behavior: "smooth", block: "start"});
}

async function loadCorrectionHistory(punchId) {
    const container = document.getElementById("punch-correction-history");
    const response = await fetch("/api/admin/punches/" + punchId + "/corrections");
    const data = await response.json();
    container.replaceChildren();
    if (!data.corrections.length) return;

    const title = document.createElement("h3");
    title.textContent = "Historial de correccions";
    container.appendChild(title);
    for (const correction of data.corrections) {
        const item = document.createElement("p");
        item.textContent =
            new Date(correction.corrected_at).toLocaleString("ca-ES") +
            " · " + correction.admin_username + " · " + correction.reason;
        container.appendChild(item);
    }
}

document.getElementById("cancel-punch-correction").addEventListener("click", () => {
    currentPunch = null;
    punchEditor.classList.add("hidden");
});

document.getElementById("save-punch-correction").addEventListener("click", async () => {
    if (!currentPunch) return;
    const message = document.getElementById("punch-correction-message");
    const localTimestamp = document.getElementById("edit-punch-timestamp").value;
    const reason = document.getElementById("edit-punch-reason").value.trim();
    message.textContent = "";

    if (!localTimestamp || !reason) {
        message.textContent = "Cal indicar la data, l'hora i el motiu.";
        return;
    }

    try {
        const response = await fetch("/api/admin/punches/" + currentPunch.id, {
            method: "PATCH",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({
                employee_id: Number(editPunchEmployee.value),
                timestamp: localTimestamp,
                type: document.getElementById("edit-punch-type").value,
                reason: reason
            })
        });
        const data = await response.json();
        if (!data.ok) {
            message.textContent = data.error;
            return;
        }
        message.textContent = "Correcció desada.";
        await loadCorrectionHistory(currentPunch.id);
        await loadPunches();
    } catch {
        message.textContent = "Error de connexió";
    }
});



function openIncidentReview(punch) {
    currentIncidentPunch = punch;
    incidentReviewEditor.classList.remove("hidden");
    document.getElementById("incident-review-original").textContent =
        punch.employee_name + " · " +
        new Date(punch.timestamp).toLocaleString("ca-ES") + " · " + punch.note;
    document.getElementById("incident-review-note").value = "";
    document.getElementById("save-incident-review").textContent = punch.incident_reviewed
        ? "Reobrir incidència"
        : "Marcar com a revisada";
    document.getElementById("incident-review-message").textContent = "";
    loadIncidentReviewHistory(punch.id);
    incidentReviewEditor.scrollIntoView({behavior: "smooth", block: "start"});
}

async function loadIncidentReviewHistory(punchId) {
    const container = document.getElementById("incident-review-history");
    container.replaceChildren();

    try {
        const response = await fetch(
            "/api/admin/punches/" + punchId + "/incident-reviews"
        );
        const data = await response.json();
        if (!data.ok || !data.reviews.length) return;

        const title = document.createElement("h3");
        title.textContent = "Historial de la incidència";
        container.appendChild(title);

        for (const review of data.reviews) {
            const item = document.createElement("p");
            const status = review.status === "reviewed" ? "Revisada" : "Reoberta";
            const note = review.note ? " · " + review.note : "";
            item.textContent =
                new Date(review.reviewed_at).toLocaleString("ca-ES") +
                " · " + review.admin_username +
                " · " + status + note;
            container.appendChild(item);
        }
    } catch {
        container.textContent = "No s'ha pogut carregar l'historial.";
    }
}


document.getElementById("cancel-incident-review").addEventListener("click", () => {
    currentIncidentPunch = null;
    incidentReviewEditor.classList.add("hidden");
});

document.getElementById("save-incident-review").addEventListener("click", async () => {
    if (!currentIncidentPunch) return;
    const message = document.getElementById("incident-review-message");
    const note = document.getElementById("incident-review-note").value.trim();
    const status = currentIncidentPunch.incident_reviewed ? "pending" : "reviewed";
    message.textContent = "";

    if (status === "pending" && !note) {
        message.textContent = "Cal indicar el motiu per reobrir la incidència.";
        return;
    }

    try {
        const response = await fetch(
            "/api/admin/punches/" + currentIncidentPunch.id + "/incident-review",
            {
                method: "POST",
                headers: adminHeaders({"Content-Type": "application/json"}),
                body: JSON.stringify({
                    status: status,
                    note: note
                })
            }
        );
        const data = await response.json();
        if (!data.ok) {
            message.textContent = data.error;
            return;
        }
        currentIncidentPunch = null;
        incidentReviewEditor.classList.add("hidden");
        await loadPunches();
    } catch {
        message.textContent = "Error de connexió";
    }
});


let restoreApplyToken = null;
let restorePollTimer = null;
let backupUsbPollTimer = null;
let lastBackupUsbState = null;

function backupUsbDescription(state) {
    if (state === "available") return "USB disponible i preparat.";
    if (state === "absent") return "No hi ha cap dispositiu USB connectat.";
    return "El dispositiu USB necessita revisió abans de continuar.";
}

async function pollBackupUsbStatus() {
    if (backupsSection.classList.contains("hidden")) return;
    try {
        const response = await fetch("/api/usb/status", {cache: "no-store"});
        const data = await response.json();
        const state = data.usb ? data.usb.state : "error";
        if (state !== lastBackupUsbState) {
            lastBackupUsbState = state;
            await loadBackups();
        }
    } catch {
        if (lastBackupUsbState !== "error") {
            lastBackupUsbState = "error";
            await loadBackups();
        }
    }
}

function startBackupUsbPolling() {
    if (backupUsbPollTimer) clearInterval(backupUsbPollTimer);
    backupUsbPollTimer = setInterval(pollBackupUsbStatus, 2000);
}

function stopBackupUsbPolling() {
    if (!backupUsbPollTimer) return;
    clearInterval(backupUsbPollTimer);
    backupUsbPollTimer = null;
    lastBackupUsbState = null;
}

async function loadBackups() {
    const usbStatus = document.getElementById("backup-usb-status");
    const backupList = document.getElementById("backup-list");
    const createButton = document.getElementById("create-backup");

    try {
        const statusResponse = await fetch("/api/usb/status", {cache: "no-store"});
        const statusData = await statusResponse.json();
        const state = statusData.usb ? statusData.usb.state : "error";
        lastBackupUsbState = state;
        usbStatus.textContent = backupUsbDescription(state);
        createButton.disabled = state !== "available";

        if (state !== "available") {
            backupList.textContent = "Connecta un USB per consultar o crear còpies.";
            return;
        }

        const response = await fetch("/api/admin/usb/backups", {cache: "no-store"});
        if (response.status === 401) {
            window.location.href = "/admin/login";
            return;
        }
        const data = await response.json();
        backupList.replaceChildren();
        if (!data.ok) {
            backupList.textContent = data.error;
            return;
        }
        if (!data.backups.length) {
            backupList.textContent = "No hi ha cap còpia de seguretat en aquest USB.";
            return;
        }

        for (const backup of data.backups) {
            const row = document.createElement("div");
            row.className = "backup-row";

            const info = document.createElement("div");
            const name = document.createElement("strong");
            name.textContent = backup.filename;
            const date = document.createElement("span");
            date.className = "hint";
            date.textContent = new Date(backup.created_at).toLocaleString("ca-ES");
            info.append(name, date);

            const restore = document.createElement("button");
            restore.type = "button";
            restore.textContent = "Restaurar";
            restore.addEventListener("click", () => prepareRestore(backup.filename, restore));

            row.append(info, restore);
            backupList.appendChild(row);
        }
    } catch {
        usbStatus.textContent = "No s'ha pogut consultar l'estat de l'USB.";
        backupList.textContent = "Error de connexió.";
        createButton.disabled = true;
    }
}

document.getElementById("create-backup").addEventListener("click", async event => {
    const button = event.currentTarget;
    const message = document.getElementById("backup-message");
    button.disabled = true;
    message.textContent = "Creant i verificant la còpia...";

    try {
        const response = await fetch("/api/admin/usb/backup", {
            method: "POST",
            headers: adminHeaders()
        });
        if (response.status === 401) {
            window.location.href = "/admin/login";
            return;
        }
        const data = await response.json();
        message.textContent = data.ok
            ? "Còpia creada i verificada: " + data.filename
            : data.error;
        if (data.ok) await loadBackups();
    } catch {
        message.textContent = "Error de connexió.";
    } finally {
        button.disabled = false;
    }
});

async function prepareRestore(filename, button) {
    const message = document.getElementById("backup-message");
    button.disabled = true;
    message.textContent = "Verificant i preparant la còpia...";
    restoreApplyToken = null;

    try {
        let response = await fetch("/api/admin/usb/authorize-restore", {
            method: "POST",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({filename})
        });
        if (response.status === 401) {
            window.location.href = "/admin/login";
            return;
        }
        let data = await response.json();
        if (!data.ok) {
            message.textContent = data.error;
            return;
        }

        response = await fetch("/api/admin/usb/prepare-restore", {
            method: "POST",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({authorization_token: data.authorization_token})
        });
        data = await response.json();
        if (!data.ok) {
            message.textContent = data.error;
            return;
        }

        restoreApplyToken = data.apply_token;
        document.getElementById("restore-selected").textContent =
            "Còpia seleccionada: " + data.filename;
        document.getElementById("restore-confirmation-text").value = "";
        document.getElementById("restore-message").textContent = "";
        document.getElementById("restore-confirmation").classList.remove("hidden");
        document.getElementById("restore-confirmation").scrollIntoView({
            behavior: "smooth",
            block: "start"
        });
        message.textContent = "Còpia verificada i preparada. Falta la confirmació final.";
    } catch {
        message.textContent = "Error de connexió.";
    } finally {
        button.disabled = false;
    }
}

document.getElementById("cancel-restore").addEventListener("click", () => {
    restoreApplyToken = null;
    document.getElementById("restore-confirmation-text").value = "";
    document.getElementById("restore-confirmation").classList.add("hidden");
});

document.getElementById("apply-restore").addEventListener("click", async event => {
    const button = event.currentTarget;
    const confirmation = document.getElementById("restore-confirmation-text").value.trim();
    const message = document.getElementById("restore-message");

    if (!restoreApplyToken) {
        message.textContent = "Cal tornar a seleccionar la còpia.";
        return;
    }
    if (confirmation !== "RESTAURAR") {
        message.textContent = "Escriu RESTAURAR exactament per confirmar.";
        return;
    }

    button.disabled = true;
    message.textContent = "Iniciant la restauració...";

    try {
        const response = await fetch("/api/admin/usb/apply-restore", {
            method: "POST",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({
                apply_token: restoreApplyToken,
                confirmation: confirmation
            })
        });
        const data = await response.json();
        if (!data.ok) {
            message.textContent = data.error;
            button.disabled = false;
            return;
        }

        restoreApplyToken = null;
        message.textContent = "Restauració en curs. No desconnectis l'USB ni apaguis el terminal.";
        pollRestoreStatus();
    } catch {
        message.textContent = "El servei s'està reiniciant. Esperant que torni a estar disponible...";
        pollRestoreStatus();
    }
});

function pollRestoreStatus() {
    clearTimeout(restorePollTimer);
    restorePollTimer = setTimeout(async () => {
        const message = document.getElementById("restore-message");
        try {
            const response = await fetch("/api/admin/usb/restore-status", {cache: "no-store"});
            if (response.status === 401) {
                message.textContent = "El servei s'ha reiniciat i la sessió ja no és vàlida. Torna a iniciar sessió per comprovar el resultat de la restauració.";
                setTimeout(() => { window.location.href = "/admin/login"; }, 2500);
                return;
            }
            const data = await response.json();
            if (!data.ok) {
                message.textContent = data.error;
                document.getElementById("apply-restore").disabled = false;
                return;
            }
            if (data.state === "success") {
                message.textContent = "Restauració completada correctament. Tornant a iniciar sessió...";
                setTimeout(() => { window.location.href = "/admin/login"; }, 2000);
                return;
            }
            if (data.state === "rollback") {
                message.textContent = "La restauració ha fallat i s'ha recuperat automàticament l'estat anterior.";
                document.getElementById("apply-restore").disabled = false;
                return;
            }
            message.textContent = "Restauració en curs. No desconnectis l'USB ni apaguis el terminal.";
        } catch {
            message.textContent = "El servei s'està reiniciant. Esperant que torni a estar disponible...";
        }
        pollRestoreStatus();
    }, 1500);
}

if (!isSupervisor) {
    document.getElementById("new-web-user").addEventListener("submit", async (event) => {
        event.preventDefault();
        const response = await fetch("/api/admin/users", {
            method: "POST",
            headers: adminHeaders({"Content-Type": "application/json"}),
            body: JSON.stringify({
                username: document.getElementById("web-username").value,
                password: document.getElementById("web-password").value,
                role: document.getElementById("web-role").value,
            }),
        });
        const data = await response.json();
        document.getElementById("web-user-message").textContent = data.ok ? "Usuari creat" : data.error;
        if (data.ok) {
            event.target.reset();
            loadWebUsers();
        }
    });
}

async function loadWebUsers() {
    const response = await fetch("/api/admin/users");
    const data = await response.json();
    const container = document.getElementById("web-users");
    container.replaceChildren();
    for (const user of data.users) {
        const row = document.createElement("div");
        row.className = "employee web-user-row";
        const actions = document.createElement("div");
        actions.className = "web-user-actions";
        const label = document.createElement("span");
        label.textContent = user.username + " (" + (user.role === "admin" ? "Administrador" : "Supervisor") + ")";
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = user.active ? "Desactivar" : "Activar";
        button.addEventListener("click", async () => {
            const result = await fetch("/api/admin/users/" + user.id, {
                method: "PATCH",
                headers: adminHeaders({"Content-Type": "application/json"}),
                body: JSON.stringify({active: !user.active}),
            });
            const payload = await result.json();
            if (!payload.ok) {
                document.getElementById("web-user-message").textContent = payload.error;
            } else {
                loadWebUsers();
            }
        });
        const passwordButton = document.createElement("button");
        passwordButton.type = "button";
        passwordButton.textContent = "Contrasenya temporal";
        const passwordForm = document.createElement("form");
        passwordForm.className = "web-user-password-form hidden";
        const passwordLabel = document.createElement("label");
        passwordLabel.textContent = "Contrasenya temporal";
        const passwordInput = document.createElement("input");
        passwordInput.type = "password";
        passwordInput.autocomplete = "new-password";
        passwordInput.minLength = 12;
        passwordInput.required = true;
        passwordLabel.appendChild(passwordInput);
        const confirmLabel = document.createElement("label");
        confirmLabel.textContent = "Confirma la contrasenya";
        const confirmInput = document.createElement("input");
        confirmInput.type = "password";
        confirmInput.autocomplete = "new-password";
        confirmInput.minLength = 12;
        confirmInput.required = true;
        confirmLabel.appendChild(confirmInput);
        const formActions = document.createElement("div");
        formActions.className = "web-user-password-actions";
        const saveButton = document.createElement("button");
        saveButton.type = "submit";
        saveButton.textContent = "Desar contrasenya";
        const cancelButton = document.createElement("button");
        cancelButton.type = "button";
        cancelButton.className = "secondary-button";
        cancelButton.textContent = "Cancel·lar";
        const formMessage = document.createElement("p");
        formMessage.className = "message";
        formMessage.setAttribute("role", "status");
        formActions.append(saveButton, cancelButton);
        passwordForm.append(passwordLabel, confirmLabel, formActions, formMessage);
        function closePasswordForm() {
            passwordForm.reset();
            formMessage.textContent = "";
            passwordForm.classList.add("hidden");
            passwordButton.setAttribute("aria-expanded", "false");
        }
        passwordButton.setAttribute("aria-expanded", "false");
        passwordButton.addEventListener("click", () => {
            if (!passwordForm.classList.contains("hidden")) {
                closePasswordForm();
                return;
            }
            container.querySelectorAll(".web-user-password-form:not(.hidden)").forEach(form => {
                form.reset();
                form.classList.add("hidden");
                const trigger = form.closest(".web-user-row")?.querySelector(".web-user-password-trigger");
                if (trigger) trigger.setAttribute("aria-expanded", "false");
            });
            passwordForm.classList.remove("hidden");
            passwordButton.setAttribute("aria-expanded", "true");
            passwordInput.focus();
        });
        passwordButton.classList.add("web-user-password-trigger");
        cancelButton.addEventListener("click", closePasswordForm);
        passwordForm.addEventListener("submit", async event => {
            event.preventDefault();
            formMessage.textContent = "";
            if (passwordInput.value !== confirmInput.value) {
                formMessage.textContent = "Les contrasenyes no coincideixen";
                return;
            }
            saveButton.disabled = true;
            try {
                const response = await fetch("/api/admin/users/" + user.id + "/temporary-password", {
                    method: "POST",
                    headers: adminHeaders({"Content-Type": "application/json"}),
                    body: JSON.stringify({password: passwordInput.value}),
                });
                const result = await response.json();
                if (!response.ok || !result.ok) {
                    formMessage.textContent = result.error || "No s'ha pogut desar la contrasenya";
                    return;
                }
                document.getElementById("web-user-message").textContent =
                    "Contrasenya temporal desada. Caldrà canviar-la al proper inici de sessió.";
                closePasswordForm();
                loadWebUsers();
            } catch {
                formMessage.textContent = "Error de connexió. Torna-ho a provar.";
            } finally {
                saveButton.disabled = false;
            }
        });
        const deleteButton = document.createElement("button");
        deleteButton.type = "button";
        deleteButton.textContent = "Eliminar";
        deleteButton.disabled = Boolean(user.active);
        deleteButton.addEventListener("click", async () => {
            if (!window.confirm("Eliminar definitivament l'usuari " + user.username + "?")) return;
            const response = await fetch("/api/admin/users/" + user.id, {
                method: "DELETE",
                headers: adminHeaders(),
            });
            const result = await response.json();
            document.getElementById("web-user-message").textContent = result.ok ? "Usuari eliminat" : result.error;
            if (result.ok) loadWebUsers();
        });
        const pending = document.createElement("span");
        pending.textContent = user.must_change_password ? "Canvi de contrasenya pendent" : "";
        pending.className = "web-user-status";
        actions.append(button, passwordButton, deleteButton);
        row.append(label, actions, pending, passwordForm);
        container.appendChild(row);
    }
}

showSectionFromHash();

async function loadLogoStatus() {
    const status = document.getElementById("logo-status");
    try {
        const response = await fetch("/api/admin/logo");
        const data = await response.json();
        status.textContent = data.custom ? "S'està utilitzant un logo personalitzat." : "S'està utilitzant el logo per defecte.";
    } catch {
        status.textContent = "Error de connexió";
    }
}

function refreshLogos() {
    document.querySelectorAll('img[src^="/branding/logo"]').forEach((image) => {
        image.src = "/branding/logo?t=" + Date.now();
    });
}

async function changeLogo(request) {
    const message = document.getElementById("logo-message");
    message.textContent = "";
    try {
        const response = await request();
        const data = await response.json();
        message.textContent = data.ok ? "Logo actualitzat" : data.error;
        if (data.ok) {
            document.getElementById("logo-file").value = "";
            refreshLogos();
        }
    } catch {
        message.textContent = "Error de connexió";
    }
    if (!isSupervisor) loadLogoStatus();
}

document.getElementById("upload-logo").addEventListener("click", () => {
    const file = document.getElementById("logo-file").files[0];
    if (!file) {
        document.getElementById("logo-message").textContent = "Cal seleccionar un fitxer";
        return;
    }
    const body = new FormData();
    body.append("logo", file);
    changeLogo(() => fetch("/api/admin/logo", {method: "POST", headers: adminHeaders(), body}));
});

document.getElementById("remove-logo").addEventListener("click", () => {
    changeLogo(() => fetch("/api/admin/logo", {method: "DELETE", headers: adminHeaders()}));
});

loadLogoStatus();

 
function leaveTypePayload(name, policy, maxValue, thresholdValue, guaranteedValue, active) {
    const max_minutes = maxValue.trim() === "" ? null : Number(maxValue);
    const auto_approve_minutes = policy === "threshold" && thresholdValue.trim() !== ""
        ? Number(thresholdValue) : null;
    const guaranteed_daily_minutes = guaranteedValue.trim() === "" ? 0 : Number(guaranteedValue);
    return {
        name: name.trim(), approval_policy: policy, max_minutes, auto_approve_minutes,
        guaranteed_daily_minutes, active
    };
}

async function leaveTypeRequest(url, method, payload) {
    const response = await fetch(url, {
        method,
        headers: adminHeaders({"Content-Type": "application/json"}),
        ...(payload === undefined ? {} : {body: JSON.stringify(payload)})
    });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "Error de connexió");
    return data;
}

async function loadLeaveTypes() {
    const container = document.getElementById("leave-types-list");
    if (!container) return;
    try {
        const response = await fetch("/api/admin/leave-types");
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || "Error de connexió");
        container.replaceChildren();
        if (!data.leave_types.length) {
            container.textContent = "Encara no hi ha tipus de permisos.";
            return;
        }
        for (const [index, item] of data.leave_types.entries()) {
            const row = document.createElement("div");
            row.className = "leave-type-row";
            const name = document.createElement("input");
            name.value = item.name;
            name.maxLength = 100;
            name.setAttribute("aria-label", "Nom del tipus");
            const policy = document.createElement("select");
            for (const [value, label] of [["manual", "Revisió manual"], ["automatic", "Automàtica"], ["threshold", "Automàtica fins a un límit"]]) {
                const option = document.createElement("option");
                option.value = value;
                option.textContent = label;
                policy.appendChild(option);
            }
            policy.value = item.approval_policy;
            const max = document.createElement("input");
            max.type = "number"; max.min = "1"; max.step = "1";
            max.placeholder = "Durada de referència (min)";
            max.setAttribute("aria-label", "Durada de referència en minuts");
            max.value = item.max_minutes ?? "";
            const guaranteed = document.createElement("input");
            guaranteed.type = "number"; guaranteed.min = "0"; guaranteed.step = "1";
            guaranteed.placeholder = "Temps garantit diari (min)";
            guaranteed.setAttribute("aria-label", "Minuts garantits diaris");
            guaranteed.value = item.guaranteed_daily_minutes ?? 0;
            const threshold = document.createElement("input");
            threshold.type = "number"; threshold.min = "1"; threshold.step = "1";
            threshold.placeholder = "Llindar automàtic diari (min)";
            threshold.setAttribute("aria-label", "Llindar d'aprovació automàtica en minuts diaris");
            threshold.value = item.auto_approve_minutes ?? "";
            const syncThreshold = () => {
                threshold.disabled = policy.value !== "threshold";
                threshold.required = !threshold.disabled;
                if (threshold.disabled) threshold.value = "";
            };
            policy.addEventListener("change", syncThreshold);
            syncThreshold();
            const activeLabel = document.createElement("label");
            activeLabel.className = "leave-type-active";
            const active = document.createElement("input");
            active.type = "checkbox"; active.checked = Boolean(item.active);
            activeLabel.append(active, " Actiu");
            const save = document.createElement("button");
            save.type = "button"; save.textContent = "Desar";
            const remove = document.createElement("button");
            remove.type = "button"; remove.textContent = "Eliminar";
            remove.disabled = Boolean(item.used);
            remove.title = item.used ? "Tipus utilitzat: només es pot desactivar" : "Eliminar definitivament";
            const status = document.createElement("span");
            status.setAttribute("role", "status");
            save.addEventListener("click", async () => {
                save.disabled = true;
                try {
                    await leaveTypeRequest("/api/admin/leave-types/" + item.id, "PUT",
                        leaveTypePayload(
                            name.value, policy.value, max.value, threshold.value,
                            guaranteed.value, active.checked
                        ));
                    status.textContent = "Desat";
                    await loadLeaveTypes();
                } catch (error) { status.textContent = error.message; }
                finally { save.disabled = false; }
            });
            remove.addEventListener("click", async () => {
                if (!confirm("Vols eliminar definitivament aquest tipus de permís?")) return;
                remove.disabled = true;
                try {
                    await leaveTypeRequest("/api/admin/leave-types/" + item.id, "DELETE");
                    await loadLeaveTypes();
                } catch (error) { status.textContent = error.message; remove.disabled = false; }
            });
            name.classList.add("leave-type-name");
            policy.classList.add("leave-type-policy");
            max.classList.add("leave-type-minutes");
            guaranteed.classList.add("leave-type-minutes");
            threshold.classList.add("leave-type-minutes");
            const handle = document.createElement("span");
            handle.className = "leave-type-drag-handle";
            handle.textContent = "⠿";
            handle.title = "Arrossega per canviar l'ordre";
            handle.setAttribute("aria-label", "Arrossega per moure " + item.name);
            handle.draggable = true;
            row.dataset.leaveTypeId = String(item.id);
            handle.addEventListener("dragstart", event => {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", String(item.id));
                row.classList.add("leave-type-dragging");
            });
            handle.addEventListener("dragend", () => {
                row.classList.remove("leave-type-dragging");
                container.querySelectorAll(".leave-type-drop-target").forEach(element =>
                    element.classList.remove("leave-type-drop-target"));
            });
            row.addEventListener("dragover", event => {
                if (!event.dataTransfer.types.includes("text/plain")) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                row.classList.add("leave-type-drop-target");
            });
            row.addEventListener("dragleave", event => {
                if (!row.contains(event.relatedTarget)) row.classList.remove("leave-type-drop-target");
            });
            row.addEventListener("drop", async event => {
                event.preventDefault();
                row.classList.remove("leave-type-drop-target");
                const sourceId = Number(event.dataTransfer.getData("text/plain"));
                if (!sourceId || sourceId === item.id) return;
                const ids = data.leave_types.map(type => type.id);
                const from = ids.indexOf(sourceId);
                const to = ids.indexOf(item.id);
                if (from < 0 || to < 0) return;
                ids.splice(to, 0, ids.splice(from, 1)[0]);
                try {
                    await leaveTypeRequest("/api/admin/leave-types/order", "PUT", { ids });
                    await loadLeaveTypes();
                } catch (error) {
                    status.textContent = error.message;
                }
            });
            const actions = document.createElement("div");
            actions.className = "leave-type-actions";
            actions.append(save, remove);
            status.className = "leave-type-status";
            row.append(handle, name, policy, max, guaranteed, threshold, activeLabel, actions, status);
            container.appendChild(row);
        }
    } catch (error) {
        container.textContent = error.message;
    }
}

const newLeaveTypeForm = document.getElementById("new-leave-type");
if (newLeaveTypeForm) newLeaveTypeForm.addEventListener("submit", async event => {
    event.preventDefault();
    const message = document.getElementById("leave-type-message");
    try {
        await leaveTypeRequest("/api/admin/leave-types", "POST", leaveTypePayload(
            document.getElementById("leave-type-name").value,
            document.getElementById("leave-type-policy").value,
            document.getElementById("leave-type-max").value,
            document.getElementById("leave-type-threshold").value,
            document.getElementById("leave-type-guaranteed").value,
            true
        ));
        newLeaveTypeForm.reset();
        message.textContent = "Tipus creat";
        await loadLeaveTypes();
    } catch (error) { message.textContent = error.message; }
});

const leaveTypeCreationPolicy = document.getElementById("leave-type-policy");
if (leaveTypeCreationPolicy) {
    const leaveTypeCreationThreshold = document.getElementById("leave-type-threshold");
    const syncCreationThreshold = () => {
        leaveTypeCreationThreshold.disabled = leaveTypeCreationPolicy.value !== "threshold";
        leaveTypeCreationThreshold.required = !leaveTypeCreationThreshold.disabled;
        if (leaveTypeCreationThreshold.disabled) leaveTypeCreationThreshold.value = "";
    };
    leaveTypeCreationPolicy.addEventListener("change", syncCreationThreshold);
    newLeaveTypeForm.addEventListener("reset", () => {
        queueMicrotask(syncCreationThreshold);
    });
    syncCreationThreshold();
}


const supervisionLeaveFilter = document.getElementById("leave-supervision-filter");
const supervisionLeaveRows = document.getElementById("leave-supervision-rows");
const supervisionLeaveMessage = document.getElementById("leave-supervision-message");

async function loadSupervisionLeaves() {
    supervisionLeaveMessage.textContent = "Carregant permisos...";
    supervisionLeaveRows.replaceChildren();
    let totalRows = 0;
    try {
        const response = await fetch("/api/admin/leaves?filter=" +
            encodeURIComponent(supervisionLeaveFilter.value));
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "Error de consulta");
        for (const leave of data.leaves) {
            const row = document.createElement("tr");
            const cells = [
                leave.started_at ? new Date(leave.started_at).toLocaleString("ca-ES") : "",
                leave.employee_name,
                leave.leave_type_name,
                leave.record_state === "needs_regularization" ? "Per regularitzar" :
                    leave.record_state === "open" ? "Obert" : "Finalitzat",
                leave.status === "approved" ? "Aprovat" :
                    leave.status === "rejected" ? "Rebutjat" : "Pendent"
            ];
            for (const value of cells) {
                const cell = document.createElement("td");
                cell.textContent = value ?? "";
                row.appendChild(cell);
            }
            const actionCell = document.createElement("td");
            const detailButton = document.createElement("button");
            detailButton.type = "button";
            detailButton.textContent = "Veure detall";
            detailButton.addEventListener("click", () => loadSupervisionLeaveDetail(leave.id));
            actionCell.appendChild(detailButton);
            row.appendChild(actionCell);
            supervisionLeaveRows.appendChild(row);
            totalRows += 1;
        }
        if (supervisionLeaveFilter.value !== "regularization") {
            const dailyResponse = await fetch("/api/admin/daily-leave-decisions?filter=" +
                encodeURIComponent(supervisionLeaveFilter.value));
            const dailyData = await dailyResponse.json();
            if (!dailyResponse.ok || !dailyData.ok) {
                throw new Error(dailyData.error || "Error de consulta de decisions diàries");
            }
            for (const decision of dailyData.daily_decisions) {
                const row = document.createElement("tr");
                const date = new Date(decision.local_date + "T12:00:00");
                const state = decision.status === "pending" ? "Excés pendent" :
                    decision.status === "approved" && decision.decision_source === "automatic"
                        ? "Aprovat automàticament" :
                    decision.status === "approved" && decision.decision_source === "system"
                        ? "Sense excés pendent" :
                    decision.status === "approved" ? "Excedent aprovat" : "Excedent rebutjat";
                const cells = [
                    Number.isNaN(date.getTime()) ? decision.local_date : date.toLocaleDateString("ca-ES"),
                    decision.employee_name,
                    decision.leave_type_name,
                    "Acumulat diari · " + decision.leave_count + " intervals",
                    state
                ];
                for (const value of cells) {
                    const cell = document.createElement("td");
                    cell.textContent = value ?? "";
                    row.appendChild(cell);
                }
                const actionCell = document.createElement("td");
                const detailButton = document.createElement("button");
                detailButton.type = "button";
                detailButton.textContent = "Revisar dia";
                detailButton.addEventListener("click", () =>
                    loadDailyLeaveDecisionDetail(decision.id));
                actionCell.appendChild(detailButton);
                row.appendChild(actionCell);
                supervisionLeaveRows.appendChild(row);
                totalRows += 1;
            }
        }
        supervisionLeaveMessage.textContent = totalRows ?
            totalRows + " permisos o decisions diàries" : "No hi ha permisos en aquest filtre.";
    } catch (error) {
        supervisionLeaveMessage.textContent = error.message;
    }
}

supervisionLeaveFilter.addEventListener("change", loadSupervisionLeaves);


const supervisionLeaveDetail = document.getElementById("leave-supervision-detail");
const supervisionLeaveDetailContent = document.getElementById("leave-supervision-detail-content");
const supervisionLeaveDetailMessage = document.getElementById("leave-supervision-detail-message");

function appendLeaveDetailLine(container, label, value) {
    const paragraph = document.createElement("p");
    const strong = document.createElement("strong");
    strong.textContent = label + ": ";
    paragraph.append(strong, document.createTextNode(value == null ? "—" : String(value)));
    container.appendChild(paragraph);
}

const leaveStateLabels = {
    open: "Obert",
    finished: "Finalitzat",
    needs_regularization: "Pendent de regularització",
    pending: "Pendent",
    approved: "Aprovat",
    rejected: "Rebutjat",
    return: "Retorn oblidat",
    late_arrival: "Arribada tardana",
    early_departure: "Sortida anticipada"
};

function leaveLabel(value) {
    return value == null ? "—" : (leaveStateLabels[value] || value);
}

function leaveDate(value) {
    if (!value) return "—";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("ca-ES");
}

function appendLeaveClassification(container, leave) {
    if (leave.record_state !== "needs_regularization" ||
        leave.status !== "pending" || leave.regularization_kind ||
        !leave.punches.some(punch =>
            punch.id === leave.start_punch_id && punch.type === "sortida")) return;

    const heading = document.createElement("h3");
    heading.textContent = "Classificar la sortida";
    const explanation = document.createElement("p");
    explanation.textContent = "Indica què va passar realment. Aquesta decisió determina quines hores es podran regularitzar.";
    const label = document.createElement("label");
    label.textContent = "Tipus de regularització ";
    const select = document.createElement("select");
    for (const [value, title] of [
        ["", "Selecciona una opció"],
        ["return", "Retorn oblidat"],
        ["early_departure", "Sortida anticipada"]
    ]) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = title;
        select.appendChild(option);
    }
    label.appendChild(select);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Confirmar classificació";
    button.disabled = true;
    select.addEventListener("change", () => { button.disabled = !select.value; });
    button.addEventListener("click", async () => {
        if (!select.value || !confirm("Confirmes la classificació com a " +
                leaveLabel(select.value).toLowerCase() + "?")) return;
        button.disabled = true;
        supervisionLeaveDetailMessage.textContent = "Desant classificació...";
        try {
            const response = await fetch("/api/admin/leaves/" + leave.id + "/classify", {
                method: "POST",
                headers: adminHeaders({"Content-Type": "application/json"}),
                body: JSON.stringify({kind: select.value})
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "No s'ha pogut classificar");
            await loadSupervisionLeaveDetail(leave.id);
            await loadSupervisionLeaves();
            supervisionLeaveDetailMessage.textContent = "Classificació desada.";
        } catch (error) {
            supervisionLeaveDetailMessage.textContent = error.message;
            button.disabled = false;
        }
    });
    container.append(heading, explanation, label, button);
}

function appendReturnRegularization(container, leave) {
    if (leave.record_state !== "needs_regularization" ||
        leave.status !== "pending" || leave.regularization_kind !== "return") return;

    const heading = document.createElement("h3");
    heading.textContent = "Regularitzar el retorn oblidat";
    const explanation = document.createElement("p");
    explanation.textContent = "Indica l'hora real de retorn, no l'hora actual. El fitxatge original es conservarà i el permís continuarà pendent d'aprovació.";
    const form = document.createElement("form");
    const dateLabel = document.createElement("label");
    dateLabel.textContent = "Data i hora real de retorn ";
    const dateInput = document.createElement("input");
    dateInput.type = "datetime-local";
    dateInput.required = true;
    dateInput.step = "60";
    dateLabel.appendChild(dateInput);
    const reasonLabel = document.createElement("label");
    reasonLabel.textContent = "Justificació ";
    const reasonInput = document.createElement("textarea");
    reasonInput.required = true;
    reasonInput.rows = 3;
    reasonInput.placeholder = "Com s'ha comprovat l'hora de retorn?";
    reasonLabel.appendChild(reasonInput);
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "Desar regularització";
    form.append(dateLabel, reasonLabel, button);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!form.reportValidity() || !reasonInput.value.trim()) {
            supervisionLeaveDetailMessage.textContent = "Cal indicar una justificació.";
            return;
        }
        const local = new Date(dateInput.value);
        if (Number.isNaN(local.getTime())) {
            supervisionLeaveDetailMessage.textContent = "Data i hora no vàlides.";
            return;
        }
        if (!confirm("Confirmes l'hora real de retorn? Aquesta operació no aprova el permís.")) return;
        button.disabled = true;
        supervisionLeaveDetailMessage.textContent = "Desant regularització...";
        try {
            const response = await fetch("/api/admin/leaves/" + leave.id + "/regularize-return", {
                method: "POST",
                headers: adminHeaders({"Content-Type": "application/json"}),
                body: JSON.stringify({
                    returned_at: local.toISOString(),
                    reason: reasonInput.value.trim()
                })
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "No s'ha pogut regularitzar");
            await loadSupervisionLeaveDetail(leave.id);
            await loadSupervisionLeaves();
            supervisionLeaveDetailMessage.textContent = "Retorn regularitzat. Permís pendent d'aprovació.";
        } catch (error) {
            supervisionLeaveDetailMessage.textContent = error.message;
            button.disabled = false;
        }
    });
    container.append(heading, explanation, form);
}

function appendEarlyDepartureRegularization(container, leave) {
    if (leave.record_state !== "needs_regularization" ||
        leave.status !== "pending" || leave.regularization_kind !== "early_departure") return;

    const heading = document.createElement("h3");
    heading.textContent = "Regularitzar la sortida anticipada";
    const explanation = document.createElement("p");
    explanation.textContent = "Indica l'hora prevista de finalització de jornada, posterior a la sortida real. No es modificarà cap fitxatge i el permís continuarà pendent d'aprovació.";
    const form = document.createElement("form");
    const dateLabel = document.createElement("label");
    dateLabel.textContent = "Data i hora prevista de finalització ";
    const dateInput = document.createElement("input");
    dateInput.type = "datetime-local";
    dateInput.required = true;
    dateInput.step = "60";
    dateLabel.appendChild(dateInput);
    const reasonLabel = document.createElement("label");
    reasonLabel.textContent = "Justificació ";
    const reasonInput = document.createElement("textarea");
    reasonInput.required = true;
    reasonInput.rows = 3;
    reasonInput.placeholder = "Com s'ha comprovat l'hora prevista de finalització?";
    reasonLabel.appendChild(reasonInput);
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "Desar regularització";
    form.append(dateLabel, reasonLabel, button);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!form.reportValidity() || !reasonInput.value.trim()) {
            supervisionLeaveDetailMessage.textContent = "Cal indicar una justificació.";
            return;
        }
        const local = new Date(dateInput.value);
        if (Number.isNaN(local.getTime())) {
            supervisionLeaveDetailMessage.textContent = "Data i hora no vàlides.";
            return;
        }
        if (!confirm("Confirmes l'hora prevista de finalització? Aquesta operació no aprova el permís.")) return;
        button.disabled = true;
        supervisionLeaveDetailMessage.textContent = "Desant regularització...";
        try {
            const response = await fetch("/api/admin/leaves/" + leave.id + "/regularize-early-departure", {
                method: "POST",
                headers: adminHeaders({"Content-Type": "application/json"}),
                body: JSON.stringify({
                    expected_ended_at: local.toISOString(),
                    reason: reasonInput.value.trim()
                })
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "No s'ha pogut regularitzar");
            await loadSupervisionLeaveDetail(leave.id);
            await loadSupervisionLeaves();
            supervisionLeaveDetailMessage.textContent = "Sortida anticipada regularitzada. Permís pendent d'aprovació.";
        } catch (error) {
            supervisionLeaveDetailMessage.textContent = error.message;
            button.disabled = false;
        }
    });
    container.append(heading, explanation, form);
}

function appendLateArrivalRegularization(container, leave) {
    if (leave.record_state !== "needs_regularization" ||
        leave.status !== "pending" || !leave.punches?.some(p => p.id === leave.start_punch_id && p.type === "entrada")) return;

    const heading = document.createElement("h3");
    heading.textContent = "Regularitzar l'arribada tardana";
    const explanation = document.createElement("p");
    explanation.textContent = "Indica l'hora prevista d'entrada, anterior o igual a l'entrada real. No es modificarà cap fitxatge i el permís continuarà pendent d'aprovació.";
    const form = document.createElement("form");
    const dateLabel = document.createElement("label");
    dateLabel.textContent = "Data i hora prevista d'entrada ";
    const dateInput = document.createElement("input");
    dateInput.type = "datetime-local";
    dateInput.required = true;
    dateInput.step = "60";
    dateLabel.appendChild(dateInput);
    const reasonLabel = document.createElement("label");
    reasonLabel.textContent = "Justificació ";
    const reasonInput = document.createElement("textarea");
    reasonInput.required = true;
    reasonInput.rows = 3;
    reasonInput.placeholder = "Com s'ha comprovat l'hora prevista d'entrada?";
    reasonLabel.appendChild(reasonInput);
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "Desar regularització";
    form.append(dateLabel, reasonLabel, button);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        if (!form.reportValidity() || !reasonInput.value.trim()) {
            supervisionLeaveDetailMessage.textContent = "Cal indicar una justificació.";
            return;
        }
        const local = new Date(dateInput.value);
        if (Number.isNaN(local.getTime())) {
            supervisionLeaveDetailMessage.textContent = "Data i hora no vàlides.";
            return;
        }
        if (!confirm("Confirmes l'hora prevista d'entrada? Aquesta operació no aprova el permís.")) return;
        button.disabled = true;
        supervisionLeaveDetailMessage.textContent = "Desant regularització...";
        try {
            const response = await fetch("/api/admin/leaves/" + leave.id + "/regularize-late-arrival", {
                method: "POST",
                headers: adminHeaders({"Content-Type": "application/json"}),
                body: JSON.stringify({
                    expected_started_at: local.toISOString(),
                    reason: reasonInput.value.trim()
                })
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "No s'ha pogut regularitzar");
            await loadSupervisionLeaveDetail(leave.id);
            await loadSupervisionLeaves();
            supervisionLeaveDetailMessage.textContent = "Arribada tardana regularitzada. Permís pendent d'aprovació.";
        } catch (error) {
            supervisionLeaveDetailMessage.textContent = error.message;
            button.disabled = false;
        }
    });
    container.append(heading, explanation, form);
}

function appendLeaveDecision(container, leave) {
    if (leave.record_state !== "finished" || leave.daily_decision_id) return;
    const heading = document.createElement("h3");
    heading.textContent = "Decisió del supervisor";
    const form = document.createElement("form");
    const actionLabel = document.createElement("label");
    actionLabel.textContent = "Decisió ";
    const action = document.createElement("select");
    action.required = true;
    const options = [
        ["", "Selecciona una decisió"],
        ["approved", "Aprovar"],
        ["rejected", "Rebutjar"]
    ];
    for (const [value, label] of options) {
        if (value === leave.status) continue;
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label;
        action.appendChild(option);
    }
    actionLabel.appendChild(action);
    const reasonLabel = document.createElement("label");
    reasonLabel.textContent = "Justificació obligatòria ";
    const reason = document.createElement("textarea");
    reason.required = true;
    reason.rows = 3;
    reasonLabel.appendChild(reason);
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "Registrar decisió";
    form.append(actionLabel, reasonLabel, button);
    form.addEventListener("submit", async event => {
        event.preventDefault();
        const justification = reason.value.trim();
        if (!form.reportValidity() || !justification || !action.value) {
            supervisionLeaveDetailMessage.textContent = "Cal seleccionar una decisió i justificar-la.";
            return;
        }
        const selected = action.value;
        const label = selected === "approved" ? "aprovar" : "rebutjar";
        if (!confirm("Vols " + label + " aquest permís? La decisió quedarà registrada a l'historial.")) return;
        button.disabled = true;
        supervisionLeaveDetailMessage.textContent = "Desant decisió...";
        try {
            const response = await fetch("/api/admin/leaves/" + leave.id + "/decision", {
                method: "POST",
                headers: adminHeaders({"Content-Type": "application/json"}),
                body: JSON.stringify({status: selected, reason: justification})
            });
            const data = await response.json();
            if (!response.ok || !data.ok) throw new Error(data.error || "No s'ha pogut registrar la decisió");
            await loadSupervisionLeaveDetail(leave.id);
            await loadSupervisionLeaves();
            supervisionLeaveDetailMessage.textContent = "Decisió registrada a l'historial.";
        } catch (error) {
            supervisionLeaveDetailMessage.textContent = error.message;
            button.disabled = false;
        }
    });
    container.append(heading, form);
}

function dailySecondsLabel(seconds) {
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return (minutes ? minutes + " min " : "") + remainder + " s";
}

async function loadDailyLeaveDecisionDetail(decisionId) {
    supervisionLeaveDetail.classList.remove("hidden");
    supervisionLeaveDetailContent.replaceChildren();
    supervisionLeaveDetailMessage.textContent = "Carregant el còmput diari...";
    try {
        const response = await fetch(
            "/api/admin/daily-leave-decisions/" + encodeURIComponent(decisionId)
        );
        const data = await response.json();
        if (!response.ok || !data.ok) {
            throw new Error(data.error || "No s'ha pogut carregar la decisió diària");
        }
        const decision = data.daily_decision;
        const root = supervisionLeaveDetailContent;
        root.classList.add("leave-detail-layout");
        const header = document.createElement("header");
        header.className = "leave-detail-header";
        const identity = document.createElement("div");
        const title = document.createElement("h3");
        title.textContent = "Decisió diària de " + decision.leave_type_name;
        const subtitle = document.createElement("p");
        subtitle.textContent = decision.employee_name + " · " + decision.local_date;
        identity.append(title, subtitle);
        const status = document.createElement("span");
        status.className = "leave-detail-status leave-detail-status-" + decision.status;
        status.textContent = "Excedent: " + leaveLabel(decision.status);
        header.append(identity, status);
        root.appendChild(header);

        const summary = document.createElement("section");
        summary.className = "leave-detail-block";
        summary.appendChild(document.createElement("h3")).textContent = "Còmput del dia";
        appendLeaveDetailLine(summary, "Intervals", decision.leaves.length);
        appendLeaveDetailLine(summary, "Total acumulat", dailySecondsLabel(decision.total_seconds));
        appendLeaveDetailLine(summary, "Minuts garantits configurats",
            decision.guaranteed_daily_minutes);
        appendLeaveDetailLine(summary, "Temps garantit reconegut",
            dailySecondsLabel(decision.guaranteed_seconds));
        appendLeaveDetailLine(summary, "Excés subjecte a decisió",
            dailySecondsLabel(decision.excess_seconds));
        appendLeaveDetailLine(summary, "Temps reconegut actualment",
            dailySecondsLabel(decision.recognized_seconds));
        root.appendChild(summary);

        const intervals = document.createElement("section");
        intervals.className = "leave-detail-block";
        intervals.appendChild(document.createElement("h3")).textContent = "Intervals inclosos";
        for (const leave of decision.leaves) {
            appendLeaveDetailLine(
                intervals,
                "Permís #" + leave.id,
                leaveDate(leave.started_at) + " → " + leaveDate(leave.ended_at) +
                    " · " + leaveLabel(leave.status) +
                    (leave.requires_supervisor ? " · requereix supervisió" : "")
            );
        }
        root.appendChild(intervals);

        const actions = document.createElement("section");
        actions.className = "leave-detail-block leave-detail-actions";
        actions.appendChild(document.createElement("h3")).textContent = "Decisió única sobre l’excés";
        if (decision.status === "approved" && decision.decision_source === "system") {
            const note = document.createElement("p");
            note.textContent = "No hi ha excés pendent de revisió; només computa el temps garantit.";
            actions.appendChild(note);
        } else {
            const form = document.createElement("form");
            const actionLabel = document.createElement("label");
            actionLabel.textContent = "Decisió ";
            const action = document.createElement("select");
            action.required = true;
            for (const [value, label] of [
                ["", "Selecciona una decisió"],
                ["approved", "Aprovar tot l’excés"],
                ["rejected", "Rebutjar tot l’excés"]
            ]) {
                if (value && value === decision.status) continue;
                const option = document.createElement("option");
                option.value = value;
                option.textContent = label;
                action.appendChild(option);
            }
            actionLabel.appendChild(action);
            const reasonLabel = document.createElement("label");
            reasonLabel.textContent = "Motiu de la decisió ";
            const reason = document.createElement("textarea");
            reason.required = true;
            reason.rows = 3;
            reasonLabel.appendChild(reason);
            const button = document.createElement("button");
            button.type = "submit";
            button.textContent = "Registrar decisió diària";
            form.append(actionLabel, reasonLabel, button);
            form.addEventListener("submit", async event => {
                event.preventDefault();
                if (!form.reportValidity() || !reason.value.trim() || !action.value) {
                    supervisionLeaveDetailMessage.textContent =
                        "Cal seleccionar una decisió i indicar-ne el motiu.";
                    return;
                }
                button.disabled = true;
                supervisionLeaveDetailMessage.textContent = "Desant decisió diària...";
                try {
                    const decisionResponse = await fetch(
                        "/api/admin/daily-leave-decisions/" + decision.id + "/decision",
                        {
                            method: "POST",
                            headers: adminHeaders({"Content-Type": "application/json"}),
                            body: JSON.stringify({
                                status: action.value, reason: reason.value.trim()
                            })
                        }
                    );
                    const result = await decisionResponse.json();
                    if (!decisionResponse.ok || !result.ok) {
                        throw new Error(result.error || "No s'ha pogut registrar la decisió");
                    }
                    await loadSupervisionLeaves();
                    await loadDailyLeaveDecisionDetail(decision.id);
                    supervisionLeaveDetailMessage.textContent =
                        "Decisió diària registrada a l’historial.";
                } catch (error) {
                    supervisionLeaveDetailMessage.textContent = error.message;
                    button.disabled = false;
                }
            });
            actions.appendChild(form);
        }
        root.appendChild(actions);

        const history = document.createElement("details");
        history.className = "leave-detail-extra";
        history.appendChild(document.createElement("summary")).textContent =
            "Historial auditable de la decisió diària";
        const historyBody = document.createElement("div");
        historyBody.className = "leave-detail-extra-body";
        const actionLabels = {
            created: "Còmput diari creat",
            total_changed: "Total diari actualitzat",
            invalidated: "Decisió invalidada per canvi del total",
            automatic_approval: "Aprovació automàtica"
        };
        for (const item of decision.decision_history) {
            const transition = item.previous_status ?
                leaveLabel(item.previous_status) + " → " + leaveLabel(item.new_status) :
                leaveLabel(item.new_status);
            appendLeaveDetailLine(
                historyBody,
                leaveDate(item.changed_at),
                (actionLabels[item.action] || "Decisió del supervisor") + " · " +
                    transition + " · " + dailySecondsLabel(item.total_seconds) + " · " +
                    (item.reviewer_name || "Sistema") +
                    (item.reason ? " · " + item.reason : "")
            );
        }
        history.appendChild(historyBody);
        root.appendChild(history);
        supervisionLeaveDetailMessage.textContent = "";
        supervisionLeaveDetail.scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) {
        supervisionLeaveDetailMessage.textContent = error.message;
    }
}

async function loadSupervisionLeaveDetail(leaveId) {
    supervisionLeaveDetail.classList.remove("hidden");
    supervisionLeaveDetailContent.replaceChildren();
    supervisionLeaveDetailMessage.textContent = "Carregant detall...";
    try {
        const response = await fetch("/api/admin/leaves/" + encodeURIComponent(leaveId));
        const data = await response.json();
        if (!response.ok || !data.ok) throw new Error(data.error || "No s'ha pogut carregar");
        const leave = data.leave;
        const root = supervisionLeaveDetailContent;
        root.classList.add("leave-detail-layout");
        const header = document.createElement("header");
        header.className = "leave-detail-header";
        const identity = document.createElement("div");
        const title = document.createElement("h3");
        title.textContent = "Permís de " + leave.leave_type_name;
        const subtitle = document.createElement("p");
        subtitle.textContent = leave.employee_name + " · " + leaveDate(leave.started_at);
        identity.append(title, subtitle);
        const statuses = document.createElement("div");
        statuses.className = "leave-detail-statuses";
        for (const [value, prefix] of [[leave.status, "Decisió"], [leave.record_state, "Registre"]]) {
            const badge = document.createElement("span");
            badge.className = "leave-detail-status leave-detail-status-" + value;
            badge.textContent = prefix + ": " + leaveLabel(value);
            statuses.appendChild(badge);
        }
        header.append(identity, statuses);
        root.appendChild(header);

        const times = document.createElement("section");
        times.className = "leave-detail-block";
        const timesHeading = document.createElement("h3");
        timesHeading.textContent = "Horaris del permís";
        const timeGrid = document.createElement("div");
        timeGrid.className = "leave-detail-time-grid";
        function addTime(label, value) {
            if (!value) return;
            const item = document.createElement("div");
            item.className = "leave-detail-time-card";
            const labelNode = document.createElement("span");
            labelNode.textContent = label;
            const timeNode = document.createElement("strong");
            const parsed = new Date(value);
            timeNode.textContent = Number.isNaN(parsed.getTime()) ? value :
                parsed.toLocaleTimeString("ca-ES", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
            const dateNode = document.createElement("small");
            dateNode.textContent = Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleDateString("ca-ES");
            item.append(labelNode, timeNode, dateNode);
            timeGrid.appendChild(item);
        }
        const startPunch = leave.punches.find(p => p.id === leave.start_punch_id);
        const isArrival = startPunch?.type === "entrada";
        addTime(isArrival ? "Entrada real" : "Sortida real", leave.started_at);
        if (leave.regularization_kind === "late_arrival") {
            addTime("Entrada prevista", leave.expected_started_at);
        } else if (leave.regularization_kind === "early_departure") {
            addTime("Finalització prevista", leave.expected_ended_at);
        } else {
            addTime(leave.regularization_kind === "return" ? "Retorn regularitzat" : "Retorn / final registrat", leave.ended_at);
        }
        times.append(timesHeading, timeGrid);
        let durationStart = null;
        let durationEnd = null;
        let durationLabel = "Durada del permís";
        if (leave.regularization_kind === "late_arrival") {
            durationStart = leave.expected_started_at;
            durationEnd = leave.started_at;
            durationLabel = "Temps d'arribada tardana";
        } else if (leave.regularization_kind === "early_departure") {
            durationStart = leave.started_at;
            durationEnd = leave.expected_ended_at;
            durationLabel = "Temps de sortida anticipada";
        } else if (!isArrival) {
            durationStart = leave.started_at;
            durationEnd = leave.ended_at;
        }
        if (durationStart && durationEnd) {
            const seconds = Math.round((new Date(durationEnd) - new Date(durationStart)) / 1000);
            if (Number.isFinite(seconds) && seconds >= 0) {
                const duration = document.createElement("p");
                duration.className = "leave-detail-duration";
                duration.textContent = durationLabel + ": " +
                    (seconds >= 60 ? Math.floor(seconds / 60) + " min " : "") +
                    (seconds % 60) + " s";
                times.appendChild(duration);
            }
        }
        root.appendChild(times);

        const actions = document.createElement("section");
        actions.className = "leave-detail-block leave-detail-actions";

        appendLeaveClassification(actions, leave);
        appendReturnRegularization(actions, leave);
        appendEarlyDepartureRegularization(actions, leave);
        appendLateArrivalRegularization(actions, leave);
        appendLeaveDecision(actions, leave);
        if (leave.record_state === "open") {
            const note = document.createElement("p");
            note.textContent = "El permís encara és obert. No es pot prendre una decisió fins que finalitzi.";
            actions.appendChild(note);
        }
        root.appendChild(actions);

        const extra = document.createElement("details");
        extra.className = "leave-detail-extra";
        const summary = document.createElement("summary");
        summary.textContent = "Informació de regularització, fitxatges i historial";
        extra.appendChild(summary);
        const detailsBody = document.createElement("div");
        detailsBody.className = "leave-detail-extra-body";
        appendLeaveDetailLine(detailsBody, "Tipus de regularització", leaveLabel(leave.regularization_kind));
        appendLeaveDetailLine(detailsBody, "Motiu", leave.regularization_reason);
        appendLeaveDetailLine(detailsBody, "Inici registrat", leaveDate(leave.started_at));
        appendLeaveDetailLine(detailsBody, "Final registrat", leaveDate(leave.ended_at));
        appendLeaveDetailLine(detailsBody, "Hora prevista d'entrada", leaveDate(leave.expected_started_at));
        appendLeaveDetailLine(detailsBody, "Hora prevista de sortida", leaveDate(leave.expected_ended_at));
        const punchHeading = document.createElement("h3");
        punchHeading.textContent = "Fitxatges originals";
        detailsBody.appendChild(punchHeading);
        if (!leave.punches.length) appendLeaveDetailLine(detailsBody, "Fitxatges", "Cap");
        for (const punch of leave.punches) {
            appendLeaveDetailLine(detailsBody, "Fitxatge #" + punch.id,
                leaveDate(punch.timestamp) + " · " + punch.type + (punch.incident ? " · incidència" : ""));
        }
        const historyHeading = document.createElement("h3");
        historyHeading.textContent = "Historial de decisions";
        detailsBody.appendChild(historyHeading);
        if (!leave.decision_history.length) {
            appendLeaveDetailLine(detailsBody, "Historial", "Sense decisions manuals");
        }
        for (const item of leave.decision_history) {
            appendLeaveDetailLine(detailsBody, leaveDate(item.changed_at),
                leaveLabel(item.previous_status) + " → " + leaveLabel(item.new_status) +
                " · " + item.reviewer_name + " · " + item.reason);
        }
        extra.appendChild(detailsBody);
        root.appendChild(extra);
        supervisionLeaveDetailMessage.textContent = "";
        supervisionLeaveDetail.scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) {
        supervisionLeaveDetailMessage.textContent = error.message;
    }
}

document.getElementById("close-leave-supervision-detail").addEventListener("click", () => {
    supervisionLeaveDetail.classList.add("hidden");
});
