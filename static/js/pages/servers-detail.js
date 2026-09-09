(function () {
  function requestSubmit(form) {
    if (!form) return;
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  }

  function initTokenToggle() {
    const input = document.getElementById("server_token");
    const btn = document.getElementById("toggle_server_token");
    if (!input || !btn || btn.dataset.vodumBound === "1") return;
    btn.dataset.vodumBound = "1";

    btn.addEventListener("click", async () => {
      if (!input.value && input.type === "password" && btn.dataset.tokenUrl) {
        btn.disabled = true;
        const error = document.getElementById("server_token_error");
        if (error) error.textContent = "";
        try {
          const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
          const response = await fetch(btn.dataset.tokenUrl, {
            method: "POST", credentials: "same-origin", cache: "no-store",
            headers: {"X-CSRF-Token": csrf, "Accept": "application/json"}
          });
          if (!response.ok || response.redirected) throw new Error("Token unavailable");
          const data = await response.json();
          if (typeof data.token !== "string") throw new Error("Token unavailable");
          // Do not overwrite a replacement typed while the request was running.
          if (!input.value) input.value = data.token;
        } catch (_) {
          if (error) error.textContent = "Unable to load the saved API key. Reload the page and try again.";
          return;
        } finally {
          btn.disabled = false;
        }
      }
      input.type = input.type === "password" ? "text" : "password";
      btn.setAttribute("aria-pressed", input.type === "text" ? "true" : "false");
    });
  }

  function initDeleteModal() {
    const deleteForm = document.getElementById("delete_form");
    const deleteButton = document.querySelector('button[form="delete_form"]');
    const deleteModal = document.getElementById("deleteServerConfirmModal");
    const deleteCancel = document.getElementById("deleteServerConfirmCancel");
    const deleteOk = document.getElementById("deleteServerConfirmOk");

    if (!deleteForm || !deleteButton || !deleteModal || !deleteCancel || !deleteOk || deleteModal.dataset.vodumBound === "1") return;
    deleteModal.dataset.vodumBound = "1";

    let allowDeleteSubmit = false;

    function openDeleteModal() {
      deleteModal.classList.remove("hidden");
      deleteModal.setAttribute("aria-hidden", "false");
    }

    function closeDeleteModal() {
      deleteModal.classList.add("hidden");
      deleteModal.setAttribute("aria-hidden", "true");
    }

    function cancelDelete() {
      allowDeleteSubmit = false;
      closeDeleteModal();
    }

    deleteButton.addEventListener("click", (event) => {
      event.preventDefault();
      openDeleteModal();
    });

    deleteCancel.addEventListener("click", cancelDelete);

    deleteOk.addEventListener("click", () => {
      allowDeleteSubmit = true;
      closeDeleteModal();
      requestSubmit(deleteForm);
    });

    deleteForm.addEventListener("submit", (event) => {
      if (allowDeleteSubmit) {
        allowDeleteSubmit = false;
        return;
      }
      event.preventDefault();
      openDeleteModal();
    });

    deleteModal.addEventListener("click", (event) => {
      if (event.target === deleteModal || event.target?.classList?.contains("bg-black/70")) cancelDelete();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !deleteModal.classList.contains("hidden")) cancelDelete();
    });
  }

  function initServerDetail() {
    initTokenToggle();
    initDeleteModal();
  }

  document.addEventListener("DOMContentLoaded", initServerDetail);
  document.addEventListener("htmx:load", initServerDetail);
})();
