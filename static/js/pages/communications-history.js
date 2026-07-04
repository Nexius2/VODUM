(function () {
  function readConfig() {
    const node = document.getElementById("comm-history-config");
    if (!node) {
      return {};
    }
    try {
      return JSON.parse(node.textContent || "{}");
    } catch (error) {
      return {};
    }
  }

  const config = readConfig();

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = value;
    }
  }

  function openModal(raw) {
    let data = {};
    try {
      data = JSON.parse(raw || "{}");
    } catch (error) {
      data = {};
    }

    setText("commHistoryModalTitle", config.detailsLabel || "Details");
    setText(
      "commHistoryModalSubtitle",
      `${data.kind_label || config.entryLabel || "Entry"}${data.name ? ` - ${data.name}` : ""}`,
    );
    setText("commHistoryModalKind", data.kind_label || "-");
    setText("commHistoryModalName", data.name || "-");
    setText("commHistoryModalUser", data.user || "-");
    setText("commHistoryModalChannel", data.channel_used || "-");
    setText("commHistoryModalStatus", data.status || "-");
    setText("commHistoryModalSentAt", window.vodumFormatDateTime ? window.vodumFormatDateTime(data.sent_at || "-") : data.sent_at || "-");
    setText("commHistoryModalError", data.error || "-");
    setText("commHistoryModalSubject", data.subject || "-");
    setText("commHistoryModalBody", data.body || "-");
    setText("commHistoryModalMeta", data.meta_json || "{}");

    const modal = document.getElementById("commHistoryModal");
    if (!modal) {
      return;
    }
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    document.body.classList.add("overflow-hidden");
  }

  function closeModal() {
    const modal = document.getElementById("commHistoryModal");
    if (!modal) {
      return;
    }
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    document.body.classList.remove("overflow-hidden");
  }

  document.querySelectorAll("tr[data-history]").forEach(function (row) {
    if (row.dataset.boundCommHistory === "1") {
      return;
    }
    row.dataset.boundCommHistory = "1";

    row.addEventListener("click", function () {
      openModal(row.dataset.history);
    });

    row.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openModal(row.dataset.history);
      }
    });
  });

  const modal = document.querySelector("[data-comm-history-modal]");
  if (modal) {
    modal.addEventListener("click", closeModal);
  }

  const panel = document.querySelector("[data-comm-history-panel]");
  if (panel) {
    panel.addEventListener("click", function (event) {
      event.stopPropagation();
    });
  }

  document.querySelectorAll("[data-comm-history-close]").forEach(function (button) {
    button.addEventListener("click", closeModal);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeModal();
    }
  });

  window.openCommHistoryModal = openModal;
  window.closeCommHistoryModal = closeModal;
})();