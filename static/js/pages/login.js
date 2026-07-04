(function vodumLoginPage() {
  const modal = document.getElementById("resetModal");
  const openBtn = document.getElementById("openResetModal");
  const closeBtn = document.getElementById("closeResetModal");
  const closeBtn2 = document.getElementById("closeResetModal2");
  const togglePasswordBtn = document.getElementById("togglePassword");
  const passwordInput = document.getElementById("password");

  function openModal() {
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  function togglePasswordVisibility() {
    if (!passwordInput) return;
    passwordInput.type = passwordInput.type === "password" ? "text" : "password";
  }

  if (openBtn) openBtn.addEventListener("click", openModal);
  if (closeBtn) closeBtn.addEventListener("click", closeModal);
  if (closeBtn2) closeBtn2.addEventListener("click", closeModal);
  if (togglePasswordBtn) togglePasswordBtn.addEventListener("click", togglePasswordVisibility);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });

  if (modal) {
    modal.addEventListener("click", (event) => {
      if (event.target === modal || event.target.classList.contains("bg-black/70")) {
        closeModal();
      }
    });
  }
})();