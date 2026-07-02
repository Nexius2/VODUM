(function vodumDashboardPage() {
  function navigateTo(url) {
    if (!url) return;
    window.location.href = url;
  }

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