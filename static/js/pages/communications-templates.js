(function () {
  function readConfig() {
    const node = document.getElementById("comm-templates-config");
    if (!node) {
      return {};
    }
    try {
      return JSON.parse(node.textContent || "{}");
    } catch (error) {
      return {};
    }
  }

  function setBlockDisabled(blockElement, disabled) {
    if (!blockElement) {
      return;
    }
    blockElement.querySelectorAll("input, select, textarea, button").forEach(function (element) {
      if (disabled) {
        element.setAttribute("disabled", "disabled");
      } else {
        element.removeAttribute("disabled");
      }
    });
  }

  function bindTemplateForm(config) {
    const toggle = document.getElementById("template_enabled_switch");
    const hidden = document.getElementById("template_enabled");

    if (toggle && hidden) {
      if (config.streamBlockedEnabledLocked) {
        hidden.value = "1";
      } else {
        toggle.addEventListener("change", function () {
          hidden.value = toggle.checked ? "1" : "0";
        });
      }
    }

    const triggerSelect = document.getElementById("trigger_event");
    const blockExpiration = document.getElementById("delay_block_expiration");
    const blockUserCreation = document.getElementById("delay_block_user_creation");
    const blockExpirationChangeDirection = document.getElementById("expiration_change_direction_block");
    const daysOffset = document.getElementById("days_offset");
    const directionSelect = document.getElementById("delay_direction_select");
    const hiddenBefore = document.getElementById("days_before_hidden");
    const hiddenAfter = document.getElementById("days_after_hidden");

    function syncHiddenDelayValues() {
      if (!daysOffset || !directionSelect || !hiddenBefore || !hiddenAfter) {
        return;
      }

      const raw = (daysOffset.value || "").trim();
      const parsed = raw === "" ? 0 : parseInt(raw, 10);
      const offset = Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;

      if ((directionSelect.value || "before") === "after") {
        hiddenBefore.value = "";
        hiddenAfter.value = String(offset);
      } else {
        hiddenAfter.value = "";
        hiddenBefore.value = String(offset);
      }
    }

    function refreshDelayUI() {
      const eventName = triggerSelect ? triggerSelect.value || "expiration" : "expiration";

      if (eventName === "user_creation" || eventName === "pending_invite_reminder") {
        blockExpiration?.classList.add("hidden");
        blockUserCreation?.classList.remove("hidden");
        blockExpirationChangeDirection?.classList.add("hidden");
        setBlockDisabled(blockExpiration, true);
        setBlockDisabled(blockUserCreation, false);
        setBlockDisabled(blockExpirationChangeDirection, true);
        return;
      }

      if (eventName === "referral_reward") {
        blockExpiration?.classList.add("hidden");
        blockUserCreation?.classList.add("hidden");
        blockExpirationChangeDirection?.classList.add("hidden");
        setBlockDisabled(blockExpiration, true);
        setBlockDisabled(blockUserCreation, true);
        setBlockDisabled(blockExpirationChangeDirection, true);
        if (hiddenBefore) hiddenBefore.value = "";
        if (hiddenAfter) hiddenAfter.value = "0";
        return;
      }

      if (eventName === "expiration_change") {
        blockExpiration?.classList.add("hidden");
        blockUserCreation?.classList.add("hidden");
        blockExpirationChangeDirection?.classList.remove("hidden");
        setBlockDisabled(blockExpiration, true);
        setBlockDisabled(blockUserCreation, true);
        setBlockDisabled(blockExpirationChangeDirection, false);
        if (hiddenBefore) hiddenBefore.value = "";
        if (hiddenAfter) hiddenAfter.value = "0";
        return;
      }

      blockUserCreation?.classList.add("hidden");
      blockExpiration?.classList.remove("hidden");
      blockExpirationChangeDirection?.classList.add("hidden");
      setBlockDisabled(blockUserCreation, true);
      setBlockDisabled(blockExpiration, false);
      setBlockDisabled(blockExpirationChangeDirection, true);
      syncHiddenDelayValues();
    }

    triggerSelect?.addEventListener("change", refreshDelayUI);
    daysOffset?.addEventListener("input", syncHiddenDelayValues);
    directionSelect?.addEventListener("change", syncHiddenDelayValues);
    refreshDelayUI();
  }

  function bindHelpModals() {
    const helpButton = document.getElementById("commVarsHelpBtn");
    const helpModal = document.getElementById("commVarsHelpModal");
    const helpCloseTop = document.getElementById("commVarsHelpCloseTop");
    const helpCloseBottom = document.getElementById("commVarsHelpCloseBottom");
    const duplicateModal = document.getElementById("duplicateDisabledModal");
    const duplicateCloseTop = document.getElementById("duplicateDisabledCloseTop");
    const duplicateCloseBottom = document.getElementById("duplicateDisabledCloseBottom");

    function openModal(modal) {
      if (!modal) return;
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal(modal) {
      if (!modal) return;
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }

    helpButton?.addEventListener("click", function () { openModal(helpModal); });
    helpCloseTop?.addEventListener("click", function () { closeModal(helpModal); });
    helpCloseBottom?.addEventListener("click", function () { closeModal(helpModal); });
    duplicateCloseTop?.addEventListener("click", function () { closeModal(duplicateModal); });
    duplicateCloseBottom?.addEventListener("click", function () { closeModal(duplicateModal); });

    helpModal?.addEventListener("click", function (event) {
      if (event.target === helpModal || event.target.classList.contains("absolute")) {
        closeModal(helpModal);
      }
    });

    duplicateModal?.addEventListener("click", function (event) {
      if (event.target === duplicateModal || event.target.classList.contains("absolute")) {
        closeModal(duplicateModal);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeModal(helpModal);
        closeModal(duplicateModal);
      }
    });
  }

  function bindRowLinks() {
    document.querySelectorAll("tr[data-href]").forEach(function (row) {
      if (row.dataset.boundRowClick === "1") {
        return;
      }
      row.dataset.boundRowClick = "1";
      row.addEventListener("click", function () {
        window.location.href = row.dataset.href;
      });
      row.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          window.location.href = row.dataset.href;
        }
      });
    });
  }

  function bindDeleteModal() {
    const deleteButton = document.getElementById("commTemplateDeleteBtn");
    const modal = document.getElementById("commTemplateDeleteModal");
    const cancelButton = document.getElementById("commTemplateDeleteCancel");
    const confirmButton = document.getElementById("commTemplateDeleteConfirm");
    const actionInput = document.getElementById("commTemplateFormAction");

    if (!deleteButton || !modal || !cancelButton || !confirmButton || !actionInput) {
      return;
    }

    const form = deleteButton.closest("form");

    function openModal() {
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }

    deleteButton.addEventListener("click", openModal);
    cancelButton.addEventListener("click", closeModal);
    confirmButton.addEventListener("click", function () {
      actionInput.value = "delete";
      form.submit();
    });
    modal.addEventListener("click", function (event) {
      if (event.target === modal || event.target.classList.contains("bg-black/70")) {
        closeModal();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !modal.classList.contains("hidden")) {
        closeModal();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    const config = readConfig();
    bindTemplateForm(config);
    bindHelpModals();
    bindRowLinks();
    bindDeleteModal();
  });
})();