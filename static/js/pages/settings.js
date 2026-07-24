(() => {
  function getModal(id) {
    if (!id) return null;
    return document.getElementById(id);
  }

  function openModal(id) {
    const modal = getModal(id);
    if (!modal) return;
    modal.classList.remove("hidden");
    if (window.VodumModal && typeof window.VodumModal.sync === "function") {
      window.VodumModal.sync(modal);
    }
  }

  function closeModal(id) {
    const modal = getModal(id);
    if (!modal) return;
    modal.classList.add("hidden");
    if (window.VodumModal && typeof window.VodumModal.sync === "function") {
      window.VodumModal.sync(modal);
    }
  }

  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-settings-modal-open]");
    if (opener) {
      event.preventDefault();
      openModal(opener.dataset.settingsModalOpen);
      return;
    }

    const closer = event.target.closest("[data-settings-modal-close]");
    if (closer) {
      event.preventDefault();
      closeModal(closer.dataset.settingsModalClose);
      return;
    }

    const modal = event.target.closest("[data-settings-modal-backdrop]");
    if (modal && event.target === modal) {
      closeModal(modal.id);
    }
  });
  function renderTotpQrCode() {
    const container = document.getElementById("totp-qr-code");
    const uriElement = document.getElementById("totp-uri-value");

    if (!container || !uriElement || !window.QRCode) return;

    const uri = uriElement.textContent.trim();
    if (!uri) return;

    container.innerHTML = "";

    new QRCode(container, {
      text: uri,
      width: 180,
      height: 180,
      correctLevel: QRCode.CorrectLevel.M,
    });
  }

  function initTotpDependencies() {
    const totp = document.getElementById("admin-totp-enabled");
    const localTrust = document.getElementById("admin-totp-local-trust-enabled");
    const localTrustOption = document.getElementById("admin-totp-local-trust-option");
    if (!totp || !localTrust || !localTrustOption || totp.dataset.vodumDependencyBound === "1") return;
    totp.dataset.vodumDependencyBound = "1";

    function syncLocalTrust() {
      const enabled = totp.checked;
      localTrust.disabled = !enabled;
      localTrustOption.classList.toggle("cursor-pointer", enabled);
      localTrustOption.classList.toggle("cursor-not-allowed", !enabled);
      localTrustOption.classList.toggle("opacity-50", !enabled);
    }

    totp.addEventListener("change", syncLocalTrust);
    syncLocalTrust();
  }

  function initNotificationOrder() {
    const list = document.getElementById("notif-order-list");
    const hidden = document.getElementById("notifications_order_hidden");
    if (!list || !hidden || list.dataset.vodumBound === "1") return;
    list.dataset.vodumBound = "1";

    function updateHidden() {
      const items = Array.from(list.querySelectorAll("li[data-channel]"));
      const order = items.map((li) => li.getAttribute("data-channel")).filter(Boolean);
      hidden.value = order.join(",");
    }

    function moveItem(li, direction) {
      if (!li) return;
      if (direction === "up") {
        const previous = li.previousElementSibling;
        if (previous) list.insertBefore(li, previous);
      } else if (direction === "down") {
        const next = li.nextElementSibling;
        if (next) list.insertBefore(next, li);
      }
      updateHidden();
    }

    list.addEventListener("click", (event) => {
      const btnUp = event.target.closest(".order-up");
      const btnDown = event.target.closest(".order-down");
      if (!btnUp && !btnDown) return;

      const li = event.target.closest("li[data-channel]");
      if (btnUp) moveItem(li, "up");
      if (btnDown) moveItem(li, "down");
    });

    updateHidden();
  }

  function initSettingsPage() {
    renderTotpQrCode();
    initTotpDependencies();
    initNotificationOrder();
  }

  document.addEventListener("DOMContentLoaded", initSettingsPage);
  document.addEventListener("htmx:load", initSettingsPage);
})();
