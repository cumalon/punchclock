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
    if (isSupervisor && section !== "punches") section = "punches";
    employeesSection.classList.toggle("hidden", section !== "employees");
    punchesSection.classList.toggle("hidden", section !== "punches");
    settingsSection.classList.toggle("hidden", section !== "settings");
    backupsSection.classList.toggle("hidden", section !== "backups");
    const usersSection = document.getElementById("users-section");
    if (usersSection) usersSection.classList.toggle("hidden", section !== "users");

    document.querySelectorAll("[data-section]").forEach(link => {
        link.classList.toggle("active", link.dataset.section === section);
    });

    document.querySelector(".page-header").classList.toggle("hidden", section !== "employees");

    if (section === "punches") loadPunches();
    if (section === "settings") loadSettings();
    if (section === "users") loadWebUsers();
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
    "#treballadors": "employees",
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
        row.className = "employee";
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
        row.append(label, button);
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
