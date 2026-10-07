let pin = "";
let employee = null;
let identificationToken = null;
let soundVolume = 20;
let pendingPunchType = null;
let usbPromptedDevice = null;
let usbSuccessVisibleUntil = 0;
let usbExportInProgress = false;
let usbAdminPin = "";

const pinScreen = document.getElementById("pin-screen");
const punchScreen = document.getElementById("punch-screen");
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

function showPinScreen() {
    employee = null;
    identificationToken = null;
    punchButtons.forEach(button => button.disabled = false);
    pin = "";
    display.textContent = "";
    punchMessage.textContent = "";
    pendingPunchType = null;
    incidentConfirmation.classList.add("hidden");
    pinKeypad.classList.remove("hidden");

    punchScreen.classList.add("hidden");
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
        employeeName.textContent = employee.name;

        pinScreen.classList.add("hidden");
        punchScreen.classList.remove("hidden");
        playPinAcceptedSound();

    } catch (error) {
        display.textContent = "Error de connexió";
        pin = "";
    }
}

async function createPunch(type, confirmIncident = false) {
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
                confirm_incident: confirmIncident
            })
        });

        const data = await response.json();

        if (!data.ok) {
            if (data.confirmation_required) {
                pendingPunchType = type;
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
        createPunch(pendingPunchType, true);
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
