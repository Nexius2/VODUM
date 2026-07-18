(function vodumDashboardPage() {
  function navigateTo(url) {
    if (!url) return;
    window.location.href = url;
  }

  document.addEventListener("htmx:beforeSwap", function (event) {
    const target = (event.detail && event.detail.target) || event.target;
    if (!target || !target.dataset || target.dataset.stableSwap !== "now-playing") return;

    const current = target.querySelector("[data-now-playing-fragment]");
    const nextHtml = String((event.detail && event.detail.serverResponse) || "").trim();
    if (!current || !nextHtml) return;

    const template = document.createElement("template");
    template.innerHTML = nextHtml;
    const next = template.content.querySelector("[data-now-playing-fragment]");
    if (!next) return;

    if (current.dataset.state === next.dataset.state && current.dataset.key === next.dataset.key) {
      event.preventDefault();
    }
  });

  function showWidgetFallback(event) {
    const target = (event.detail && event.detail.target) || event.target;
    if (!target?.dataset?.dashboardWidgetFallback) return;

    const fallback = document.createElement("div");
    fallback.className = "min-h-24 flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/40 px-4 text-sm text-slate-400";
    fallback.textContent = target.dataset.dashboardWidgetFallback;
    target.replaceChildren(fallback);
  }

  ["htmx:timeout", "htmx:sendError", "htmx:responseError"].forEach((eventName) => {
    document.addEventListener(eventName, showWidgetFallback);
  });

  document.addEventListener("click", function (event) {
    const closeButton = event.target.closest("[data-dashboard-modal-close]");
    if (closeButton) {
      const modal = document.getElementById(closeButton.dataset.dashboardModalClose || "");
      if (modal) {
        modal.classList.add("hidden");
      }
      return;
    }

    const link = event.target.closest("[data-dashboard-link]");
    if (link) {
      navigateTo(link.dataset.dashboardLink);
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;

    const link = event.target.closest("[data-dashboard-link]");
    if (!link) return;

    event.preventDefault();
    navigateTo(link.dataset.dashboardLink);
  });
})();
