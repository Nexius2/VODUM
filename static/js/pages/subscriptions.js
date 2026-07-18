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

  function readJsonConfig(id) {
    const element = document.getElementById(id);
    if (!element) return {};
    try { return JSON.parse(element.textContent || "{}"); }
    catch (error) { console.error(`Invalid JSON configuration in #${id}`, error); return {}; }
  }

  function bindPoliciesTable() {
    const tableBody = document.getElementById("policyTableBody");
    if (!tableBody || tableBody.dataset.vodumBound === "1") return;
    tableBody.dataset.vodumBound = "1";

    const rows = Array.from(tableBody.querySelectorAll(".policy-row"));
    const byId = (id) => document.getElementById(id);
    const filters = ["policyFilterSearch", "policyFilterStatus", "policyFilterScope", "policyFilterProvider", "policyFilterOrigin"].map(byId);
    const pageSize = byId("policyPageSize");
    const reset = byId("policyFilterReset");
    const previous = byId("policyPrevPage");
    const next = byId("policyNextPage");
    const summary = byId("policyTableSummary");
    const indicator = byId("policyPageIndicator");
    const selectAll = byId("policySelectAll");
    const deleteButton = byId("policyBulkDeleteBtn");
    const deleteCount = byId("policyBulkDeleteCount");
    const deleteInputs = byId("policyBulkDeleteInputs");
    const deleteForm = byId("policyBulkDeleteForm");
    const modal = byId("policyBulkDeleteModal");
    const modalBackdrop = byId("policyBulkDeleteModalBackdrop");
    const modalCancel = byId("policyBulkDeleteModalCancel");
    const modalConfirm = byId("policyBulkDeleteModalConfirm");
    const modalCount = byId("policyBulkDeleteModalCount");
    const modalPlural = byId("policyBulkDeleteModalPlural");
    if (filters.some((item) => !item) || !pageSize || !previous || !next || !summary || !indicator) return;

    const config = readJsonConfig("subscription-policies-config");
    const normalize = (value) => String(value || "").trim().toLowerCase();
    let currentPage = 1;
    let visibleRows = [];

    function selectedCheckboxes() {
      return rows.map((row) => row.querySelector(".policy-row-checkbox")).filter((item) => item?.checked);
    }

    function visibleCheckboxes() {
      return visibleRows.filter((row) => row.dataset.deletable === "1").map((row) => row.querySelector(".policy-row-checkbox")).filter(Boolean);
    }

    function syncSelection() {
      const selected = selectedCheckboxes();
      const visible = visibleCheckboxes();
      const visibleSelected = visible.filter((item) => item.checked);
      if (deleteInputs) {
        deleteInputs.replaceChildren(...selected.map((checkbox) => {
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "policy_ids";
          input.value = checkbox.value;
          return input;
        }));
      }
      if (deleteCount) deleteCount.textContent = `(${selected.length})`;
      if (deleteButton) deleteButton.disabled = selected.length === 0;
      if (selectAll) {
        selectAll.disabled = visible.length === 0;
        selectAll.checked = visible.length > 0 && visibleSelected.length === visible.length;
        selectAll.indeterminate = visibleSelected.length > 0 && visibleSelected.length < visible.length;
      }
    }

    function filteredRows() {
      const [search, status, scope, provider, origin] = filters.map((item) => normalize(item.value));
      return rows.filter((row) => (!search || normalize(row.dataset.search).includes(search))
        && (!status || normalize(row.dataset.status) === status)
        && (!scope || normalize(row.dataset.scope) === scope)
        && (!provider || normalize(row.dataset.provider) === provider)
        && (!origin || normalize(row.dataset.origin) === origin));
    }

    function render() {
      const filtered = filteredRows();
      const size = Number.parseInt(pageSize.value || "20", 10);
      const pages = Math.max(1, Math.ceil(filtered.length / size));
      currentPage = Math.min(Math.max(currentPage, 1), pages);
      const start = (currentPage - 1) * size;
      visibleRows = filtered.slice(start, start + size);
      rows.forEach((row) => { row.style.display = "none"; });
      visibleRows.forEach((row) => { row.style.display = ""; });
      summary.textContent = filtered.length
        ? String(config.showing_results || "{from}-{to} / {total}").replace("{from}", start + 1).replace("{to}", Math.min(start + size, filtered.length)).replace("{total}", filtered.length)
        : config.zero_results || "0";
      indicator.textContent = `${currentPage} / ${pages}`;
      previous.disabled = currentPage <= 1;
      next.disabled = currentPage >= pages;
      [previous, next].forEach((button) => {
        button.classList.toggle("opacity-50", button.disabled);
        button.classList.toggle("cursor-not-allowed", button.disabled);
      });
      syncSelection();
    }

    function closeModal() {
      modal?.classList.add("hidden");
      document.body.classList.remove("overflow-hidden");
    }
    function openModal() {
      const count = selectedCheckboxes().length;
      if (!count || !modal) return;
      if (modalCount) modalCount.textContent = String(count);
      if (modalPlural) modalPlural.textContent = count > 1 ? config.selected_policies : config.selected_policy;
      modal.classList.remove("hidden");
      document.body.classList.add("overflow-hidden");
    }

    filters.forEach((filter) => ["input", "change"].forEach((name) => filter.addEventListener(name, () => { currentPage = 1; render(); })));
    pageSize.addEventListener("change", () => { currentPage = 1; render(); });
    reset?.addEventListener("click", () => {
      filters.forEach((filter) => { filter.value = ""; });
      pageSize.value = "20";
      rows.forEach((row) => { const checkbox = row.querySelector(".policy-row-checkbox"); if (checkbox) checkbox.checked = false; });
      currentPage = 1;
      render();
    });
    previous.addEventListener("click", () => { currentPage -= 1; render(); });
    next.addEventListener("click", () => { currentPage += 1; render(); });
    rows.forEach((row) => row.querySelector(".policy-row-checkbox")?.addEventListener("change", syncSelection));
    selectAll?.addEventListener("change", () => { visibleCheckboxes().forEach((checkbox) => { checkbox.checked = selectAll.checked; }); syncSelection(); });
    deleteButton?.addEventListener("click", openModal);
    modalCancel?.addEventListener("click", closeModal);
    modalBackdrop?.addEventListener("click", closeModal);
    modalConfirm?.addEventListener("click", () => { if (selectedCheckboxes().length) deleteForm?.submit(); else closeModal(); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !modal?.classList.contains("hidden")) closeModal(); });
    render();
  }
  function initSubscriptionsPage() {
    bindSubscriptionApplyConfirm();
    bindSubscriptionApplicationsFilters();
    renderPlanSummaries();
    bindPlansEnabledOnly();
    bindTemplateDeleteConfirm();
    bindSubscriptionSettingsExpiryMode();
    bindPoliciesTable();
  }

  document.addEventListener("DOMContentLoaded", initSubscriptionsPage);
  document.addEventListener("htmx:load", initSubscriptionsPage);
})();
