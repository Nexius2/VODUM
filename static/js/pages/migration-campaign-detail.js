(function () {
  const modal = document.getElementById("migration-credentials-modal");
  const username = document.getElementById("migration-credential-username");
  const password = document.getElementById("migration-credential-password");
  const error = document.getElementById("migration-credentials-error");
  const closeButton = document.getElementById("migration-credentials-close");

  if (!modal || !username || !password || !error || !closeButton) {
    return;
  }

  function csrfToken() {
    return (
      document.querySelector('input[name="_csrf_token"]')?.value ||
      document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") ||
      ""
    );
  }

  function closeModal() {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    username.textContent = "";
    password.textContent = "";
    error.classList.add("hidden");
  }

  closeButton.addEventListener("click", closeModal);
  modal.addEventListener("click", function (event) {
    if (event.target === modal) {
      closeModal();
    }
  });

  document.querySelectorAll(".migration-reveal-credentials").forEach(function (button) {
    button.addEventListener("click", async function () {
      username.textContent = "";
      password.textContent = "";
      error.classList.add("hidden");
      modal.classList.remove("hidden");
      modal.classList.add("flex");

      try {
        const response = await fetch(button.dataset.url, {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken() },
          credentials: "same-origin",
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "request_failed");
        }
        username.textContent = data.username || "";
        password.textContent = data.password || "";
      } catch (requestError) {
        error.classList.remove("hidden");
      }
    });
  });
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm || "Confirm?")) {
        event.preventDefault();
      }
    });
  });
})();
