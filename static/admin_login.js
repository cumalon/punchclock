const loginForm = document.getElementById("admin-login");
loginForm.addEventListener("submit", async event => {
    event.preventDefault();
    const response = await fetch("/api/admin/login", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            username: document.getElementById("username").value,
            password: document.getElementById("password").value
        })
    });
    const data = await response.json();
    if (response.ok) {
        window.location.href = "/admin";
    } else {
        document.getElementById("login-message").textContent = data.error;
    }
});
