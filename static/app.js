let pin = "";
let employee = null;
let identificationToken = null;
let soundVolume = 20;
let pendingPunchType = null;
let pendingReturnChoice = null;
let usbPromptedDevice = null;
let usbSuccessVisibleUntil = 0;
let usbExportInProgress = false;
let usbAdminPin = "";

const pinScreen = document.getElementById("pin-screen");
const punchScreen = document.getElementById("punch-screen");
const leaveScreen = document.getElementById("leave-screen");
const leaveConfirmScreen = document.getElementById("leave-confirm-screen");
let leaveContext = null;
let selectedLeaveDirection = null;
let leaveRegisterBusy = false;
const leaveOptionsSelect = document.getElementById("leave-options-select");
const continueLeaveOptions = document.getElementById("continue-leave-options");
const leaveOptionsMessage = document.getElementById("leave-options-message");
const pinKeypad = document.querySelector(".keypad");
const display = document.getElementById("pin-display");
const employeeName = document.getElementById("employee-name");
const punchMessage = document.getElementById("punch-message");
const punchButtons = document.querySelectorAll("[data-punch]");
const incidentConfirmation = document.getElementById("incident-confirmation");
const incidentMessage = document.getElementById("incident-message");
const usbDialog = document.getElementById("usb-dialog");
const usbMessage = document.getElementById("usb-message");
const usbQuestion = document.getElementById("usb-question");
const usbAuth = document.getElementById("usb-auth");
const usbPinDisplay = document.getElementById("usb-pin-display");
const usbKeypad = document.getElementById("usb-keypad");


async function loadKioskSettings() {
    try {
        const response = await fetch("/api/settings");
        const data = await response.json();
        if (data.ok) soundVolume = data.settings.sound_volume;
    } catch {
        soundVolume = 0;
    }
}

function playTone(frequency, duration) {
    if (soundVolume <= 0) return;

    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextClass) return;

    const context = new AudioContextClass();
    const oscillator = context.createOscillator();
    const gain = context.createGain();

    oscillator.frequency.value = frequency;
    gain.gain.value = 0.12 * (soundVolume / 20);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + duration);
    oscillator.addEventListener("ended", () => context.close());
}

function playPinAcceptedSound() {
    playTone(880, 0.12);
}

function playPunchConfirmationSound() {
    playTone(880, 0.18);
}

function playErrorSound() {
    playTone(330, 0.16);
}

function updateClock() {
    const now = new Date();

    document.getElementById("clock").textContent =
        now.toLocaleTimeString("ca-ES", {
            hour: "2-digit",
            minute: "2-digit"
        });

    document.getElementById("date").textContent =
        now.toLocaleDateString("ca-ES", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric"
        });
}

function updatePinDisplay() {
    display.textContent = "●".repeat(pin.length);
}

const KIOSK_INACTIVITY_MS = 30000;
let kioskInactivityTimer = null;

function resetKioskInactivity() {
    clearTimeout(kioskInactivityTimer);
    kioskInactivityTimer = null;
    if (identificationToken) {
        kioskInactivityTimer = setTimeout(showPinScreen, KIOSK_INACTIVITY_MS);
    }
}

document.addEventListener("pointerdown", () => {
    if (identificationToken) resetKioskInactivity();
}, {passive: true});
document.addEventListener("keydown", () => {
    if (identificationToken) resetKioskInactivity();
});

function showPinScreen() {
    clearTimeout(kioskInactivityTimer);
    kioskInactivityTimer = null;
    employee = null;
    identificationToken = null;
    punchButtons.forEach(button => button.disabled = false);
    pin = "";
    display.textContent = "";
    punchMessage.textContent = "";
    pendingPunchType = null;
    pendingReturnChoice = null;
    document.getElementById("ordinary-leave-return-screen").classList.add("hidden");
    incidentConfirmation.classList.add("hidden");
    pinKeypad.classList.remove("hidden");

    punchScreen.classList.add("hidden");
    leaveScreen.classList.add("hidden");
    leaveConfirmScreen.classList.add("hidden");
    leaveContext = null;
    selectedLeaveDirection = null;
    leaveOptionsSelect.replaceChildren(new Option("Selecciona un permís", ""));
    document.getElementById("frequent-leave-options").replaceChildren();
    document.getElementById("frequent-leave-options").classList.add("hidden");
    leaveOptionsSelect.disabled = true;
    continueLeaveOptions.disabled = true;
    pinScreen.classList.remove("hidden");
}

async function identify() {
    await loadKioskSettings();

    if (!pin) {
        return;
    }

    try {
        const response = await fetch("/api/identify", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({ pin })
        });

        const data = await response.json();
        pin = "";

        if (!data.ok) {
            if (response.status === 429) {
                display.textContent = "Massa intents incorrectes. Identificació bloquejada temporalment. Torna-ho a provar d'aquí a un minut.";
                pinKeypad.classList.add("hidden");
                setTimeout(showPinScreen, 3000);
            } else {
                display.textContent = "PIN incorrecte";
            }
            playErrorSound();
            return;
        }

        employee = data.employee;
        identificationToken = data.identification_token;
        resetKioskInactivity();
        employeeName.textContent = employee.name;

        pinScreen.classList.add("hidden");
        punchScreen.classList.remove("hidden");
        playPinAcceptedSound();

    } catch (error) {
        display.textContent = "Error de connexió";
        pin = "";
    }
}

async function createPunch(type, confirmIncident = false, returnChoice = null) {
    await loadKioskSettings();

    if (!employee || !identificationToken) {
        return;
    }

    punchButtons.forEach(button => button.disabled = true);

    try {
        const response = await fetch("/api/punch", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                identification_token: identificationToken,
                type: type,
                confirm_incident: confirmIncident,
                return_choice: returnChoice
            })
        });

        const data = await response.json();

        if (!data.ok) {
            if (data.return_choice_required) {
                pendingPunchType = type;
                pendingReturnChoice = null;
                const leaveName = data.leave && (data.leave.leave_type_name || data.leave.name) || "permís";
                document.getElementById("ordinary-leave-return-message").textContent =
                    "Tens un permís obert: " + leaveName + ". Quan has tornat?";
                document.getElementById("ordinary-leave-now").disabled = type !== "entrada";
                punchScreen.classList.add("hidden");
                document.getElementById("ordinary-leave-return-screen").classList.remove("hidden");
                return;
            }
            if (data.return_entry_required) {
                punchMessage.textContent = data.error || "Cal registrar una entrada de retorn";
                punchButtons.forEach(button => button.disabled = false);
                return;
            }
            if (data.confirmation_required) {
                pendingPunchType = type;
                pendingReturnChoice = returnChoice;
                document.getElementById("ordinary-leave-return-screen").classList.add("hidden");
                punchScreen.classList.remove("hidden");
                incidentMessage.replaceChildren();
                const situation = document.createElement("span");
                situation.textContent = data.error + ".";
                const question = document.createElement("span");
                question.textContent = "Vols registrar-ho igualment?";
                incidentMessage.append(situation, question);
                incidentConfirmation.classList.remove("hidden");
                punchButtons.forEach(button => button.disabled = true);
                playErrorSound();
                return;
            }
            punchMessage.textContent = data.error || "No s'ha pogut registrar";
            playErrorSound();
            setTimeout(showPinScreen, 3000);
            return;
        }

        punchMessage.textContent =
            returnChoice === "now" ? "Permís finalitzat i entrada registrada" :
            returnChoice === "earlier" ? "Fitxatge registrat. Permís pendent de regularització." :
            type === "entrada"
                ? "Entrada registrada"
                : "Sortida registrada";

        playPunchConfirmationSound();
        setTimeout(showPinScreen, 2000);

    } catch (error) {
        punchMessage.textContent = "Error de connexió";
        setTimeout(showPinScreen, 3000);
    }
}

async function checkUsbStatus() {
    try {
        const response = await fetch("/api/usb/status", {cache: "no-store"});
        const data = await response.json();
        if (!data.ok) return;

        if (data.usb.state === "available") {
            if (usbPromptedDevice !== data.usb.device) {
                usbPromptedDevice = data.usb.device;
                usbQuestion.classList.remove("hidden");
                usbMessage.textContent = "";
                usbAdminPin = "";
                updateUsbPinDisplay();
                usbAuth.classList.remove("hidden");
                usbDialog.classList.remove("hidden");
            }
            return;
        }

        if (data.usb.state === "absent") {
            if (usbExportInProgress || Date.now() < usbSuccessVisibleUntil) return;
            usbPromptedDevice = null;
            usbAdminPin = "";
            updateUsbPinDisplay();
            usbDialog.classList.add("hidden");
            usbMessage.textContent = "";
        }
    } catch {
        // A transient status error must not interrupt normal timeclock use.
    }
}


document.querySelectorAll(".keypad button").forEach(button => {
    button.addEventListener("click", () => {
        const action = button.dataset.action;

        if (action === "clear") {
            pin = "";
            updatePinDisplay();
        } else if (action === "enter") {
            identify();
        } else if (pin.length < 8) {
            pin += button.textContent.trim();
            updatePinDisplay();
        }
    });
});

document.getElementById("confirm-incident").addEventListener("click", () => {
    if (pendingPunchType) {
        incidentConfirmation.classList.add("hidden");
        createPunch(pendingPunchType, true, pendingReturnChoice);
    }
});

document.getElementById("cancel-incident").addEventListener("click", showPinScreen);
const cancelPunchButton = document.getElementById("cancel-punch");
if (cancelPunchButton) cancelPunchButton.addEventListener("click", showPinScreen);

function updateUsbPinDisplay() {
    usbPinDisplay.textContent = "●".repeat(usbAdminPin.length);
}

usbKeypad.querySelectorAll("button").forEach(button => {
    button.addEventListener("click", () => {
        const action = button.dataset.action;
        if (action === "clear") {
            usbAdminPin = "";
        } else if (button.type === "submit") {
            usbAuth.requestSubmit();
            return;
        } else if (usbAdminPin.length < 6) {
            usbAdminPin += button.textContent.trim();
        }
        updateUsbPinDisplay();
    });
});

document.getElementById("usb-auth-cancel").addEventListener("click", () => {
    usbAdminPin = "";
    updateUsbPinDisplay();
    usbDialog.classList.add("hidden");
});

usbAuth.addEventListener("submit", async event => {
    event.preventDefault();
    if (usbAdminPin.length !== 6) {
        usbAdminPin = "";
        updateUsbPinDisplay();
        usbMessage.textContent = "El PIN ha de tenir 6 dígits.";
        playErrorSound();
        return;
    }

    usbMessage.textContent = "Comprovant PIN...";
    usbKeypad.querySelectorAll("button").forEach(button => button.disabled = true);

    try {
        const response = await fetch("/api/usb/authorize-export", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({pin: usbAdminPin})
        });
        const data = await response.json();
        usbAdminPin = "";
        updateUsbPinDisplay();

        if (!data.ok) {
            usbMessage.textContent = data.error || "No s'ha pogut autoritzar";
            playErrorSound();
            usbKeypad.querySelectorAll("button").forEach(button => button.disabled = false);
            return;
        }

        usbMessage.textContent = "Exportant fitxatges. No retiris el dispositiu USB...";
        usbExportInProgress = true;

        const exportResponse = await fetch("/api/usb/export", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({authorization_token: data.authorization_token})
        });
        const exportData = await exportResponse.json();
        usbExportInProgress = false;
        usbKeypad.querySelectorAll("button").forEach(button => button.disabled = false);

        if (!exportData.ok) {
            usbSuccessVisibleUntil = Date.now() + 10000;
            usbMessage.textContent = exportData.error || "No s'han pogut exportar els fitxatges";
            playErrorSound();
            return;
        }

        usbSuccessVisibleUntil = Date.now() + 10000;
        usbMessage.textContent = "Exportació completada: " + exportData.filename + ". Ja pots retirar el dispositiu USB.";
        playPunchConfirmationSound();
    } catch {
        usbExportInProgress = false;
        usbAdminPin = "";
        updateUsbPinDisplay();
        usbKeypad.querySelectorAll("button").forEach(button => button.disabled = false);
        usbMessage.textContent = "Error de connexió";
        playErrorSound();
    }
});

document.querySelectorAll("[data-punch]").forEach(button => {
    button.addEventListener("click", () => {
        createPunch(button.dataset.punch);
    });
});

loadKioskSettings();
updateClock();
setInterval(updateClock, 1000);
checkUsbStatus();
setInterval(checkUsbStatus, 2000);


async function showLeaveOptions() {
    if (!identificationToken) return;
    punchScreen.classList.add("hidden");
    leaveScreen.classList.remove("hidden");
    leaveOptionsSelect.replaceChildren(new Option("Selecciona un permís", ""));
    document.getElementById("frequent-leave-options").replaceChildren();
    document.getElementById("frequent-leave-options").classList.add("hidden");
    leaveOptionsSelect.disabled = true;
    continueLeaveOptions.disabled = true;
    leaveOptionsMessage.textContent = "Carregant permisos...";
    try {
        const response = await fetch("/api/leave/options", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({identification_token: identificationToken})
        });
        const data = await response.json();
        if (!data.ok) {
            leaveOptionsMessage.textContent = data.error || "No s'han pogut consultar els permisos";
            return;
        }
        leaveContext = data.context;
        if (data.context.open_leave) {
            leaveOptionsMessage.textContent =
                "Tens un permís pendent de finalitzar: " + data.context.open_leave.leave_type_name;
            document.getElementById("finish-leave-choice").classList.remove("hidden");
            return;
        }
        if (!data.leave_types.length) {
            leaveOptionsMessage.textContent = "No hi ha tipus de permís disponibles";
            return;
        }
        leaveOptionsMessage.textContent = "Selecciona un tipus de permís (consulta de prova)";
        for (const kind of data.leave_types) {
            leaveOptionsSelect.add(new Option(kind.name, String(kind.id)));
        }
        leaveOptionsSelect.disabled = false;
        const frequentContainer = document.getElementById("frequent-leave-options");
        for (const id of (data.frequent_leave_type_ids || []).slice(0, 2)) {
            const kind = data.leave_types.find(item => item.id === id);
            if (!kind) continue;
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = kind.name;
            button.addEventListener("click", () => {
                leaveOptionsSelect.value = String(kind.id);
                continueLeaveOptions.disabled = false;
                continueLeaveOptions.click();
            });
            frequentContainer.appendChild(button);
        }
        frequentContainer.classList.toggle("hidden", !frequentContainer.childElementCount);
    } catch {
        leaveOptionsMessage.textContent = "Error de connexió";
    }
}

document.getElementById("show-leave-options").addEventListener("click", showLeaveOptions);
document.getElementById("cancel-leave-options").addEventListener("click", () => {
    leaveScreen.classList.add("hidden");
    punchScreen.classList.remove("hidden");
});

leaveOptionsSelect.addEventListener("change", () => {
    continueLeaveOptions.disabled = !leaveOptionsSelect.value;
});
continueLeaveOptions.addEventListener("click", () => {
    if (!leaveOptionsSelect.value || !leaveContext) return;
    document.getElementById("leave-confirm-name").textContent =
        leaveOptionsSelect.selectedOptions[0].textContent;
    const hint = document.getElementById("leave-confirm-hint");
    const suggested = leaveContext.suggested_direction;
    hint.textContent = leaveContext.requires_direction_choice
        ? "Hi ha una entrada anterior sense sortida. Tria explícitament l'acció."
        : "Acció proposada segons l'últim fitxatge:";
    document.querySelectorAll("[data-leave-direction]").forEach(button => {
        button.disabled = false;
        button.style.background = !leaveContext.requires_direction_choice &&
            button.dataset.leaveDirection === suggested ? "var(--accent)" : "";
    });
    selectedLeaveDirection = null;
    const registerButton = document.getElementById("leave-register");
    registerButton.classList.add("hidden");
    registerButton.textContent = "CONFIRMAR REGISTRE";
    registerButton.onclick = null;
    registerButton.disabled = false;
    document.getElementById("leave-confirm-back").disabled = false;
    document.getElementById("leave-direction-actions").classList.remove("hidden");
    document.getElementById("leave-finish-register").classList.add("hidden");
    document.getElementById("leave-finish-register").dataset.confirmIncident = "false";
    document.getElementById("leave-confirm-message").textContent =
        "Selecciona una direcció abans de confirmar el registre.";
    leaveScreen.classList.add("hidden");
    leaveConfirmScreen.classList.remove("hidden");
});
document.querySelectorAll("[data-leave-direction]").forEach(button => {
    button.addEventListener("click", () => {
        if (leaveRegisterBusy) return;
        selectedLeaveDirection = button.dataset.leaveDirection;
        leaveStartConfirmIncident = false;
        const registerButton = document.getElementById("leave-register");
        registerButton.textContent = "CONFIRMAR REGISTRE";
        document.getElementById("leave-confirm-message").textContent =
            (selectedLeaveDirection === "entrada" ? "Entrada" : "Sortida") +
            " amb permís. Prem CONFIRMAR REGISTRE per desar-ho.";
        document.getElementById("leave-register").classList.remove("hidden");
    });
});
let leaveStartConfirmIncident = false;
document.getElementById("leave-register").addEventListener("click", async () => {
    if (leaveRegisterBusy || !selectedLeaveDirection || !leaveOptionsSelect.value ||
        !identificationToken) return;
    leaveRegisterBusy = true;
    const registerButton = document.getElementById("leave-register");
    const backButton = document.getElementById("leave-confirm-back");
    registerButton.disabled = true;
    backButton.disabled = true;
    document.querySelectorAll("[data-leave-direction]").forEach(b => b.disabled = true);
    const message = document.getElementById("leave-confirm-message");
    message.textContent = "Registrant permís...";
    try {
        const response = await fetch("/api/leave/start", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                identification_token: identificationToken,
                leave_type_id: Number(leaveOptionsSelect.value),
                type: selectedLeaveDirection,
                confirm_incident: leaveStartConfirmIncident
            })
        });
        const data = await response.json();
        if (data.ok) {
            identificationToken = null;
            message.textContent = "Permís i fitxatge registrats correctament.";
            playPunchConfirmationSound();
            setTimeout(showPinScreen, 3000);
        } else if (data.confirmation_required && !leaveStartConfirmIncident) {
            leaveStartConfirmIncident = true;
            message.textContent = (data.error || "Incidència de fitxatge") +
                ". No s'ha registrat res. Cal confirmar la incidència.";
            registerButton.textContent = "CONFIRMAR INCIDÈNCIA I REGISTRAR";
            registerButton.disabled = false;
            backButton.disabled = false;
        } else {
            message.textContent = data.error || "No s'ha pogut registrar el permís";
            registerButton.disabled = false;
            backButton.disabled = false;
        }
    } catch {
        message.textContent = "Error de connexió. Comprova el registre abans de repetir.";
        backButton.disabled = false;
        registerButton.disabled = false;
    } finally {
        leaveRegisterBusy = false;
    }
});
document.getElementById("leave-confirm-back").addEventListener("click", () => {
    leaveConfirmScreen.classList.add("hidden");
    leaveScreen.classList.remove("hidden");
});

let leaveFinishBusy = false;
document.getElementById("finish-leave-choice").addEventListener("click", () => {
    if (!leaveContext || !leaveContext.open_leave) return;
    document.getElementById("leave-confirm-name").textContent =
        leaveContext.open_leave.leave_type_name;
    document.getElementById("leave-confirm-hint").textContent =
        "El retorn finalitzarà el permís i registrarà una ENTRADA amb l'hora actual.";
    document.getElementById("leave-direction-actions").classList.add("hidden");
    document.getElementById("leave-register").classList.add("hidden");
    document.getElementById("leave-finish-register").classList.remove("hidden");
    document.getElementById("leave-finish-register").disabled = false;
    document.getElementById("leave-finish-register").dataset.confirmIncident = "false";
    document.getElementById("leave-finish-register").textContent = "CONFIRMAR RETORN";
    document.getElementById("leave-confirm-message").textContent =
        "Prem CONFIRMAR RETORN per registrar l'entrada.";
    leaveScreen.classList.add("hidden");
    leaveConfirmScreen.classList.remove("hidden");
});
document.getElementById("leave-finish-register").addEventListener("click", async () => {
    if (leaveFinishBusy || !identificationToken) return;
    const button = document.getElementById("leave-finish-register");
    const back = document.getElementById("leave-confirm-back");
    const message = document.getElementById("leave-confirm-message");
    const confirmIncident = button.dataset.confirmIncident === "true";
    leaveFinishBusy = true;
    button.disabled = true;
    back.disabled = true;
    message.textContent = "Registrant retorn...";
    try {
        const response = await fetch("/api/leave/finish", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                identification_token: identificationToken,
                confirm_incident: confirmIncident
            })
        });
        const data = await response.json();
        if (data.ok) {
            identificationToken = null;
            button.classList.add("hidden");
            message.textContent = "Retorn registrat. Permís finalitzat correctament.";
            playPunchConfirmationSound();
            setTimeout(showPinScreen, 3000);
        } else if (data.confirmation_required && !confirmIncident) {
            message.textContent = (data.error || "Incidència") +
                ". No s'ha registrat res. Confirma només si és correcte.";
            button.dataset.confirmIncident = "true";
            button.textContent = "CONFIRMAR INCIDÈNCIA I RETORN";
            button.disabled = false;
            back.disabled = false;
            playErrorSound();
        } else {
            message.textContent = data.error || "No s'ha pogut registrar el retorn";
            button.disabled = false;
            back.disabled = false;
        }
    } catch {
        message.textContent = "Error de connexió. Comprova el registre abans de repetir.";
        back.disabled = false;
    } finally {
        leaveFinishBusy = false;
    }
});

function chooseOrdinaryLeaveReturn(choice) {
    if (!pendingPunchType) return;
    const type = pendingPunchType;
    pendingReturnChoice = choice;
    document.getElementById("ordinary-leave-return-screen").classList.add("hidden");
    punchScreen.classList.remove("hidden");
    createPunch(type, false, choice);
}
document.getElementById("ordinary-leave-now").addEventListener("click", () => chooseOrdinaryLeaveReturn("now"));
document.getElementById("ordinary-leave-earlier").addEventListener("click", () => chooseOrdinaryLeaveReturn("earlier"));
document.getElementById("ordinary-leave-cancel").addEventListener("click", showPinScreen);
