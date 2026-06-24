// Shared accessibility and lifecycle layer for VODUM modals.
(() => {
  const SELECTOR = ".fixed.inset-0.z-50";
  const FOCUSABLE = [
    "[autofocus]",
    "button:not([disabled])",
    "a[href]",
    "input:not([disabled]):not([type='hidden'])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])"
  ].join(",");
  const CLOSE_CONTROL = [
    "[data-vodum-modal-close]",
    "[data-modal-close]",
    "button[id*='Close']",
    "button[id*='close']",
    "button[id*='Cancel']",
    "button[id*='cancel']",
    "[onclick*='close']"
  ].join(",");

  const openers = new WeakMap();

  function isOpen(modal) {
    return !modal.classList.contains("hidden") && modal.getAttribute("aria-hidden") !== "true";
  }

  function modalElements(root = document) {
    const found = Array.from(root.querySelectorAll?.(SELECTOR) || []);
    if (root instanceof Element && root.matches(SELECTOR)) found.unshift(root);
    return [...new Set(found)];
  }

  function syncBodyLock() {
    document.body.classList.toggle(
      "overflow-hidden",
      modalElements().some(isOpen)
    );
  }

  function focusModal(modal) {
    if (modal.contains(document.activeElement)) return;
    const target = modal.querySelector(FOCUSABLE) || modal;
    requestAnimationFrame(() => target.focus({ preventScroll: true }));
  }

  function prepare(modal) {
    if (modal.dataset.vodumModalReady === "1") return;
    modal.dataset.vodumModalReady = "1";
    modal.setAttribute("role", modal.getAttribute("role") || "dialog");
    modal.setAttribute("aria-modal", "true");
    if (!modal.hasAttribute("tabindex")) modal.tabIndex = -1;
    modal.setAttribute("aria-hidden", modal.classList.contains("hidden") ? "true" : "false");
  }

  function sync(modal) {
    prepare(modal);
    const open = !modal.classList.contains("hidden");
    modal.setAttribute("aria-hidden", open ? "false" : "true");

    if (open) {
      if (!openers.has(modal)) openers.set(modal, document.activeElement);
      focusModal(modal);
    } else {
      const opener = openers.get(modal);
      openers.delete(modal);
      if (opener instanceof HTMLElement && opener.isConnected) {
        requestAnimationFrame(() => opener.focus({ preventScroll: true }));
      }
    }
    syncBodyLock();
  }

  function bind(root = document) {
    modalElements(root).forEach(sync);
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = modalElements().filter(isOpen);
    const modal = open.at(-1);
    if (!modal) return;
    const close = modal.querySelector(CLOSE_CONTROL);
    if (close instanceof HTMLElement) {
      event.preventDefault();
      close.click();
    }
  });

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === "attributes" && mutation.target.matches?.(SELECTOR)) {
        sync(mutation.target);
      }
      mutation.addedNodes.forEach((node) => {
        if (node instanceof Element) bind(node);
      });
    }
  });

  function init() {
    bind();
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["class"],
      childList: true,
      subtree: true
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
  document.addEventListener("htmx:load", (event) => bind(event.target));

  window.VodumModal = { bind, sync };
})();
