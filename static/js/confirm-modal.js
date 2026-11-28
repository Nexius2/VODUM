// Themed confirmation dialog (instead of window.confirm).
// window.vodumConfirm({title, message, confirmLabel, danger}) -> Promise<boolean>
// Forms with data-confirm ask before submitting; data-confirm-title and
// data-confirm-label set the title and the button text.
// data-confirm-danger="0" uses the normal (non red) button.
(() => {
  if (window.vodumConfirm) return;
  const modal = () => document.getElementById("vodum-confirm-modal");
  let pending = null;

  function close(result) {
    const root = modal();
    if (!root || !pending) return;
    root.classList.add("hidden");
    root.setAttribute("aria-hidden", "true");
    const { resolve, opener } = pending;
    pending = null;
    opener?.focus?.();
    resolve(result);
  }

  window.vodumConfirm = (options = {}) => {
    const root = modal();
    if (!root) return Promise.resolve(false);
    if (pending) close(false);
    root.querySelector("#vodum-confirm-title").textContent = options.title || root.dataset.defaultTitle || "";
    root.querySelector("#vodum-confirm-message").textContent = options.message || "";
    const ok = root.querySelector("[data-vodum-confirm-ok]");
    ok.dataset.defaultLabel = ok.dataset.defaultLabel || ok.textContent;
    ok.textContent = options.confirmLabel || ok.dataset.defaultLabel;
    ok.classList.toggle("bg-rose-700", options.danger !== false);
    ok.classList.toggle("hover:bg-rose-800", options.danger !== false);
    ok.classList.toggle("bg-primary", options.danger === false);
    ok.classList.toggle("hover:bg-primary-dark", options.danger === false);
    return new Promise((resolve) => {
      pending = { resolve, opener: document.activeElement };
      root.classList.remove("hidden");
      root.setAttribute("aria-hidden", "false");
      root.querySelector("[data-vodum-confirm-cancel]").focus();
    });
  };

  document.addEventListener("click", (event) => {
    if (!pending) return;
    if (event.target.closest("[data-vodum-confirm-ok]")) close(true);
    else if (event.target.closest("[data-vodum-confirm-cancel]") || event.target === modal()) close(false);
  });
  document.addEventListener("keydown", (event) => {
    if (pending && event.key === "Escape") close(false);
  });

  // Forms: ask first, then submit again with the same submit button.
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.confirm) return;
    if (form.dataset.confirmed === "1") {
      delete form.dataset.confirmed;
      return;
    }
    event.preventDefault();
    const submitter = event.submitter;
    window.vodumConfirm({
      title: form.dataset.confirmTitle,
      message: form.dataset.confirm,
      confirmLabel: form.dataset.confirmLabel,
      danger: form.dataset.confirmDanger !== "0",
    }).then((confirmed) => {
      if (!confirmed) return;
      form.dataset.confirmed = "1";
      if (submitter && form.requestSubmit) form.requestSubmit(submitter);
      else form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  }, true);
})();
