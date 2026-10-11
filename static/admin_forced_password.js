document.getElementById("forced-change").addEventListener("submit", async event => {
    event.preventDefault();
    const response = await fetch("/api/admin/complete-password-change", {
        method: "POST",
        headers: {"Content-Type": "application/json", "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]').content},
        body: JSON.stringify({
            temporary_password: document.getElementById("temporary").value,
            new_password: document.getElementById("new").value,
            confirmation: document.getElementById("confirm").value,
        }),
    });
    const result = await response.json();
    if (result.ok) window.location.href = "/admin/login";
    else document.getElementById("message").textContent = result.error;
});