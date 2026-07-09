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

  document.addEventListener("DOMContentLoaded", renderTotpQrCode);
})();
