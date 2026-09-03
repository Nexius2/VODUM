(function vodumPortalBase() {
  document.querySelectorAll("[data-admin-preview] form").forEach((form) => {
    form.addEventListener("submit", (event) => event.preventDefault());
  });

  const modal = document.querySelector("[data-payment-modal]");
  const openButton = document.querySelector("[data-payment-open]");
  if (!modal || !openButton) return;

  const closeButton = modal.querySelector("[data-payment-close]");
  const show = () => {
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    closeButton?.focus();
  };
  const hide = () => {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    openButton.focus();
  };

  openButton.addEventListener("click", show);
  modal.querySelectorAll("[data-payment-close]").forEach((button) => {
    button.addEventListener("click", hide);
  });
  modal.addEventListener("click", (event) => {
    if (event.target === modal) hide();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) hide();
  });
})();
