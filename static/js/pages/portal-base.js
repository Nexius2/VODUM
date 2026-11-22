(function vodumPortalBase() {
  const header = document.querySelector("[data-portal-header]");
  const menuToggle = header?.querySelector("[data-portal-menu-toggle]");
  if (menuToggle) {
    const mobile = window.matchMedia("(max-width: 767px)");
    const menu = header.querySelector("#portal-navigation");
    const menuIsOpen = () => menuToggle.getAttribute("aria-expanded") === "true";
    const setMenuOpen = (open) => {
      header.toggleAttribute("data-portal-menu-open", open);
      menuToggle.setAttribute("aria-expanded", String(open));
    };
    menuToggle.addEventListener("click", () => {
      setMenuOpen(!menuIsOpen());
      if (menuIsOpen()) {
        const activeLink = menu.querySelector('[aria-current="page"]:not([data-portal-primary])');
        (activeLink || menu.querySelector("a:not([data-portal-primary]), button"))?.focus();
      }
    });
    header.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && mobile.matches && menuIsOpen()) {
        event.preventDefault();
        setMenuOpen(false);
        menuToggle.focus();
      }
    });
    document.addEventListener("pointerdown", (event) => {
      if (menuIsOpen() && !header.contains(event.target)) setMenuOpen(false);
    });
    mobile.addEventListener("change", (event) => {
      if (!event.matches) setMenuOpen(false);
    });
    header.setAttribute("data-portal-menu-ready", "");
  }

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
