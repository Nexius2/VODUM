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
      // Retry off-screen at most once per minute; never replace a healthy text card.
      if (current.dataset.artworkFailed === "1" && current.dataset.state === "idle") {
        const now = Date.now();
        const lastRetry = Number(current.dataset.artworkRetryAt || 0);
        const nextImage = next.querySelector(".js-quote-artwork");
        const slot = current.querySelector("[data-quote-artwork-slot]");
        if (nextImage && slot && now - lastRetry >= 60000) {
          current.dataset.artworkRetryAt = String(now);
          const probe = new Image();
          probe.onload = () => {
            if (!current.isConnected || probe.naturalWidth === 0) return;
            const image = nextImage.cloneNode(true);
            image.src = probe.src;
            image.classList.remove("opacity-0");
            slot.replaceChildren(image);
            delete current.dataset.artworkFailed;
          };
          const source = new URL(nextImage.src, window.location.href);
          source.searchParams.set("vodum_retry", String(Math.floor(now / 60000)));
          probe.src = source.href;
        }
      }
    }
  });

  function showWidgetFallback(event) {
    const target = (event.detail && event.detail.target) || event.target;
    if (!target?.dataset?.dashboardWidgetFallback) return;

    // Keep the last successful snapshot during a transient refresh failure.
    if (target.dataset.dashboardLoaded === "1") return;

    const fallback = document.createElement("div");
    fallback.className = "min-h-24 flex items-center justify-center rounded-xl border border-slate-800 bg-slate-950/40 px-4 text-sm text-slate-400";
    fallback.textContent = target.dataset.dashboardWidgetFallback;
    target.replaceChildren(fallback);
  }

  document.addEventListener("htmx:afterSwap", function (event) {
    const target = event.detail?.target || event.target;
    if (target?.dataset?.dashboardWidgetFallback) target.dataset.dashboardLoaded = "1";
  });

  document.addEventListener("htmx:beforeRequest", function (event) {
    // Background dashboard polling need not compete with the visible page.
    if (document.hidden && event.detail?.elt?.hasAttribute("data-dashboard-widget-fallback")) {
      event.preventDefault();
    }
  });

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
