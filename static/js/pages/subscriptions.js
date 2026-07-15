(function () {
  function requestSubmit(form) {
    if (!form) return;
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  }

  function bindSubscriptionApplyConfirm() {
    const modal = document.getElementById("subscriptionApplyConfirmModal");
    const btnCancel = document.getElementById("subscriptionApplyConfirmCancel");
    const btnOk = document.getElementById("subscriptionApplyConfirmOk");
    const forms = Array.from(document.querySelectorAll(".js-subscription-confirm-form"));

    if (!modal || !btnCancel || !btnOk || !forms.length || modal.dataset.vodumBound === "1") return;
    modal.dataset.vodumBound = "1";

    let pendingForm = null;
    let allowSubmit = false;

    function openModal() {
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }

    function reset() {
      pendingForm = null;
      allowSubmit = false;
      closeModal();
    }

    forms.forEach((form) => {
      form.addEventListener("submit", (event) => {
        if (allowSubmit) {
          allowSubmit = false;
          return;
        }

        event.preventDefault();
        pendingForm = form;
        openModal();
      });
    });

    btnCancel.addEventListener("click", reset);
    btnOk.addEventListener("click", () => {
      if (!pendingForm) return;
      const confirmInput = pendingForm.querySelector('input[name="confirm_replace"]');
      if (confirmInput) confirmInput.value = "1";
      allowSubmit = true;
      closeModal();
      requestSubmit(pendingForm);
    });

    modal.addEventListener("click", (event) => {
      if (event.target === modal || event.target?.classList?.contains("bg-black/70")) reset();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.classList.contains("hidden")) reset();
    });
  }

  function bindSubscriptionApplicationsFilters() {
    document.querySelectorAll(".js-subscription-user-select").forEach((select) => {
      if (select.dataset.vodumBound === "1") return;
      select.dataset.vodumBound = "1";
      select.addEventListener("change", () => requestSubmit(select.closest("form")));
    });

    const searchInput = document.getElementById("subscriptionUsersSearch");
    const searchForm = searchInput ? searchInput.closest("form") : null;
    if (!searchInput || !searchForm || searchInput.dataset.vodumBound === "1") return;
    searchInput.dataset.vodumBound = "1";

    let timer = null;
    searchInput.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => requestSubmit(searchForm), 500);
    });
    searchInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      clearTimeout(timer);
      requestSubmit(searchForm);
    });
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[char]));
  }

  function summarizePolicy(policy) {
    const rule = policy.rule || {};
    if (policy.rule_type === "max_streams_per_user") return `${rule.max ?? "?"} streams`;
    if (policy.rule_type === "max_ips_per_user") return `${rule.max ?? "?"} IPs`;
    if (policy.rule_type === "max_streams_per_ip") return `${rule.max ?? "?"} streams / IP`;
    if (policy.rule_type === "max_transcodes_global") return `${rule.max ?? "?"} transcodes`;
    if (policy.rule_type === "max_bitrate_kbps") return `${rule.max_kbps ?? "?"} kbps`;
    if (policy.rule_type === "device_allowlist") return `Devices: ${(rule.allowed || []).join(", ") || "-"}`;
    if (policy.rule_type === "ban_4k_transcode") return "No 4K transcode";
    return policy.rule_type || "Policy";
  }

  function renderPlanSummaries() {
    document.querySelectorAll(".js-plan-card").forEach((card) => {
      if (card.dataset.vodumSummaryBound === "1") return;
      card.dataset.vodumSummaryBound = "1";

      const box = card.querySelector(".js-plan-summary");
      if (!box) return;

      let policies = [];
      try { policies = JSON.parse(card.dataset.policies || "[]") || []; }
      catch (_) { policies = []; }

      if (!policies.length) return;

      box.innerHTML = policies.slice(0, 4).map((policy) => {
        const enabledClass = policy.is_enabled
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
          : "border-slate-700 bg-slate-800 text-slate-400";
        return `<span class="rounded-full border px-2 py-1 ${enabledClass}">${escapeHtml(summarizePolicy(policy))}</span>`;
      }).join("");

      if (policies.length > 4) {
        box.innerHTML += `<span class="rounded-full border border-slate-800 bg-slate-900 px-2 py-1 text-slate-400">+${policies.length - 4}</span>`;
      }
    });
  }

  function bindPlansEnabledOnly() {
    const enabledOnly = document.getElementById("plansEnabledOnly");
    if (!enabledOnly || enabledOnly.dataset.vodumBound === "1") return;
    enabledOnly.dataset.vodumBound = "1";

    const applyEnabledFilter = () => {
      document.querySelectorAll(".js-plan-card").forEach((card) => {
        const shouldHide = enabledOnly.checked && card.dataset.enabled !== "1";
        card.classList.toggle("hidden", shouldHide);
      });
    };

    enabledOnly.addEventListener("change", applyEnabledFilter);
    applyEnabledFilter();
  }

  function bindTemplateDeleteConfirm() {
    const modal = document.getElementById("templateDeleteConfirmModal");
    const nameBox = document.getElementById("templateDeleteConfirmName");
    const btnCancel = document.getElementById("templateDeleteConfirmCancel");
    const btnOk = document.getElementById("templateDeleteConfirmOk");
    const forms = Array.from(document.querySelectorAll(".js-template-delete-form"));

    if (!modal || !nameBox || !btnCancel || !btnOk || !forms.length || modal.dataset.vodumBound === "1") return;
    modal.dataset.vodumBound = "1";

    let pendingForm = null;

    function openModal(form) {
      pendingForm = form;
      nameBox.textContent = form.dataset.templateName || "-";
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      pendingForm = null;
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }

    forms.forEach((form) => {
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        openModal(form);
      });
    });

    btnCancel.addEventListener("click", closeModal);
    btnOk.addEventListener("click", () => {
      if (!pendingForm) return;
      const form = pendingForm;
      pendingForm = null;
      form.submit();
    });
    modal.addEventListener("click", (event) => {
      if (event.target === modal || event.target?.classList?.contains("bg-black/70")) closeModal();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.classList.contains("hidden")) closeModal();
    });
  }


  function bindSubscriptionSettingsExpiryMode() {
    const checkbox = document.getElementById("usage_risk_send_stream_blocked_message");
    const radios = Array.from(document.querySelectorAll('input[name="expiry_mode"]'));
    if (!checkbox || !radios.length || checkbox.dataset.vodumExpiryBound === "1") return;
    checkbox.dataset.vodumExpiryBound = "1";

    const manualChecked = checkbox.dataset.currentManualValue === "1";

    function syncStreamBlockedCheckbox() {
      const selected = document.querySelector('input[name="expiry_mode"]:checked');
      const mode = selected ? selected.value : "none";
      const forced = mode === "warn_only" || mode === "warn_then_disable";

      if (forced) {
        checkbox.checked = true;
        checkbox.disabled = true;
      } else {
        checkbox.disabled = false;
        checkbox.checked = manualChecked;
      }
    }

    radios.forEach((radio) => radio.addEventListener("change", syncStreamBlockedCheckbox));
    syncStreamBlockedCheckbox();
  }
  function initSubscriptionsPage() {
    bindSubscriptionApplyConfirm();
    bindSubscriptionApplicationsFilters();
    renderPlanSummaries();
    bindPlansEnabledOnly();
    bindTemplateDeleteConfirm();
    bindSubscriptionSettingsExpiryMode();
  }

  document.addEventListener("DOMContentLoaded", initSubscriptionsPage);
  document.addEventListener("htmx:load", initSubscriptionsPage);
})();
