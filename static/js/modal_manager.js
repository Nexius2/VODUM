// Shared accessibility and lifecycle layer for VODUM modals.
(() => {
  const LEGACY_SELECTOR = ".fixed.inset-0.z-50";
  const SELECTOR = ".fixed.inset-0:not(#mobileMenu)";
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
  const EXPLICIT_CLOSE_CONTROL = [
    "[data-vodum-modal-close]",
    "[data-modal-close]",
    "[data-settings-modal-close]",
    "[data-dashboard-modal-close]",
    "[data-comm-history-close]",
    "[data-gift-modal-close]",
    "[data-campaign-delete-close]",
    "button[id*='Close']",
    "button[id*='close']",
    "[onclick*='close']"
  ].join(",");

  const openers = new WeakMap();

  function isOpen(modal) {
    return !modal.classList.contains("hidden") && modal.getAttribute("aria-hidden") !== "true";
  }

  function modalElements(root = document) {
    const found = Array.from(root.querySelectorAll?.(SELECTOR) || []);
    if (root instanceof Element && root.matches(SELECTOR)) found.unshift(root);
    return [...new Set(found)].filter((element) => {
      const marker = `${element.id || ""} ${element.getAttribute("role") || ""}`.toLowerCase();
      return marker.includes("modal") || marker.includes("dialog") || Boolean(element.querySelector(CLOSE_CONTROL));
    });
  }

  function closeControl(modal) {
    return modal.querySelector(EXPLICIT_CLOSE_CONTROL) || modal.querySelector(CLOSE_CONTROL);
  }

  function modalPanel(modal) {
    const viewports = Array.from(modal.querySelectorAll(":scope .vodum-modal-viewport"));
    if (viewports.length) return viewports.at(-1);

    return Array.from(modal.children).find((child) => {
      if (!(child instanceof HTMLElement)) return false;
      if (child.matches(".absolute.inset-0, [data-settings-modal-backdrop]")) return false;
      return true;
    }) || null;
  }

  function normalizeCloseButton(modal) {
    if (modal.dataset.vodumCloseNormalized === "1") return;
    const explicit = modal.querySelector(EXPLICIT_CLOSE_CONTROL);
    const fallback = modal.querySelector(CLOSE_CONTROL);
    if (!(fallback instanceof HTMLElement)) return;

    let close = explicit;
    if (!(close instanceof HTMLButtonElement)) {
      close = document.createElement("button");
      close.type = "button";
      close.dataset.vodumModalCloseProxy = "1";
      close.addEventListener("click", () => fallback.click());
    }

    modal.dataset.vodumCloseNormalized = "1";
    const oldLabel = (close.getAttribute("aria-label") || close.textContent || "Close").trim();
    close.setAttribute("aria-label", oldLabel || "Close");
    close.setAttribute("title", oldLabel || "Close");
    close.textContent = "×";
    close.className = "vodum-modal-close absolute right-3 top-3 z-20 inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-700 bg-slate-950/80 text-2xl leading-none text-slate-300 shadow hover:bg-slate-800 hover:text-white focus:outline-none focus:ring-2 focus:ring-indigo-500";

    const panel = modalPanel(modal);
    if (panel instanceof HTMLElement) {
      panel.classList.add("relative");
      // Keep the close control first in scrollable panels. Besides being the
      // natural keyboard order, this prevents its static position from
      // drifting to the bottom if positioning styles load late.
      panel.prepend(close);
    }

    modal.querySelectorAll(EXPLICIT_CLOSE_CONTROL).forEach((other) => {
      if (other !== close && other instanceof HTMLElement) other.classList.add("hidden");
    });
  }

  function requestClose(modal) {
    const close = closeControl(modal);
    if (close instanceof HTMLElement && !close.hasAttribute("disabled")) {
      close.click();
    }
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
    normalizeCloseButton(modal);
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
    if (closeControl(modal) instanceof HTMLElement) {
      event.preventDefault();
      requestClose(modal);
    }
  });

  document.addEventListener("click", (event) => {
    const open = modalElements().filter(isOpen);
    const modal = open.at(-1);
    if (!modal || !modal.contains(event.target)) return;

    const panel = modalPanel(modal);
    if (panel instanceof HTMLElement && panel.contains(event.target)) return;

    requestClose(modal);
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
