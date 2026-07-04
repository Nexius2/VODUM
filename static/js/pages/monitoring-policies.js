(function () {
  const root = document;

  function readPoliciesConfig() {
    const el = document.getElementById("monitoring-policies-config");
    if (!el) return {};

    try {
      return JSON.parse(el.textContent || "{}");
    } catch (_) {
      return {};
    }
  }

  const config = readPoliciesConfig();
  const labels = config.labels || {};
  const hits30d = Array.isArray(config.hits30d) ? config.hits30d : [];
  const rule30d = Array.isArray(config.rule30d) ? config.rule30d : [];
  const provider30d = Array.isArray(config.provider30d) ? config.provider30d : [];
  const scopeNow = Array.isArray(config.scopeNow) ? config.scopeNow : [];
  const topUsers30d = Array.isArray(config.topUsers30d) ? config.topUsers30d : [];

  function label(key, fallback) {
    const value = labels[key];
    return value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function getOrCreate(el, factory) {
    if (!el) return null;
    if (el._chartInstance) return el._chartInstance;
    el._chartInstance = factory();
    return el._chartInstance;
  }

  function destroyIfNeeded(el) {
    if (el && el._chartInstance) {
      try { el._chartInstance.destroy(); } catch (_) {}
      el._chartInstance = null;
    }
  }

  function buildPoliciesCharts() {
    if (typeof Chart === "undefined") return;

    const elHits = root.getElementById("chartPolicyHits30d");
    const elRules = root.getElementById("chartPolicyRules30d");
    const elScopes = root.getElementById("chartPolicyScopes");
    const elProviders = root.getElementById("chartPolicyProviders30d");
    const elTopUsers = root.getElementById("chartPolicyTopUsers30d");

    if (!elHits || !elRules || !elScopes || !elProviders || !elTopUsers) return;

    const commonGrid = { color: "rgba(148,163,184,0.10)" };
    const commonTicks = { color: "#94A3B8" };

    destroyIfNeeded(elHits);
    destroyIfNeeded(elRules);
    destroyIfNeeded(elScopes);
    destroyIfNeeded(elProviders);
    destroyIfNeeded(elTopUsers);

    getOrCreate(elHits, () => new Chart(elHits.getContext("2d"), {
      type: "line",
      data: {
        labels: hits30d.map(x => x.day),
        datasets: [
          {
            label: label("warnAction", "Warn"),
            data: hits30d.map(x => x.warn_count || 0),
            borderColor: "#F59E0B",
            backgroundColor: "rgba(245,158,11,0.15)",
            tension: 0.35,
            fill: true
          },
          {
            label: label("killAction", "Kill"),
            data: hits30d.map(x => x.kill_count || 0),
            borderColor: "#F43F5E",
            backgroundColor: "rgba(244,63,94,0.12)",
            tension: 0.35,
            fill: true
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { labels: { color: "#CBD5E1" } }
        },
        scales: {
          x: { ticks: commonTicks, grid: commonGrid },
          y: { ticks: commonTicks, grid: commonGrid, beginAtZero: true }
        }
      }
    }));

    getOrCreate(elRules, () => new Chart(elRules.getContext("2d"), {
      type: "bar",
      data: {
        labels: rule30d.map(x => x.label),
        datasets: [
          {
            label: label("total", "Total"),
            data: rule30d.map(x => x.total || 0),
            backgroundColor: "rgba(99,102,241,0.70)",
            borderColor: "#6366F1",
            borderWidth: 1,
            borderRadius: 8
          }
        ]
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#CBD5E1" } }
        },
        scales: {
          x: { ticks: commonTicks, grid: commonGrid, beginAtZero: true },
          y: { ticks: commonTicks, grid: { display: false } }
        }
      }
    }));

    getOrCreate(elScopes, () => new Chart(elScopes.getContext("2d"), {
      type: "doughnut",
      data: {
        labels: scopeNow.map(x => x.label),
        datasets: [{
          data: scopeNow.map(x => x.value || 0),
          backgroundColor: ["#6366F1", "#14B8A6", "#F59E0B"],
          borderColor: "#0F172A",
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { color: "#CBD5E1" } }
        }
      }
    }));

    getOrCreate(elProviders, () => new Chart(elProviders.getContext("2d"), {
      type: "doughnut",
      data: {
        labels: provider30d.map(x => x.label),
        datasets: [{
          data: provider30d.map(x => x.value || 0),
          backgroundColor: ["#8B5CF6", "#06B6D4", "#10B981"],
          borderColor: "#0F172A",
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { color: "#CBD5E1" } }
        }
      }
    }));

    getOrCreate(elTopUsers, () => new Chart(elTopUsers.getContext("2d"), {
      type: "bar",
      data: {
        labels: topUsers30d.map(x => x.label),
        datasets: [
          {
            label: label("warnAction", "Warn"),
            data: topUsers30d.map(x => x.warn_count || 0),
            backgroundColor: "rgba(245,158,11,0.70)",
            borderColor: "#F59E0B",
            borderWidth: 1,
            borderRadius: 8
          },
          {
            label: label("killAction", "Kill"),
            data: topUsers30d.map(x => x.kill_count || 0),
            backgroundColor: "rgba(244,63,94,0.70)",
            borderColor: "#F43F5E",
            borderWidth: 1,
            borderRadius: 8
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: "#CBD5E1" } }
        },
        scales: {
          x: { ticks: commonTicks, grid: { display: false } },
          y: { ticks: commonTicks, grid: commonGrid, beginAtZero: true }
        }
      }
    }));
  }

  function bindPolicyEnforcementRows() {
    const modal = document.getElementById("policyEnforcementModal");
    const modalClose = document.getElementById("policyEnforcementModalClose");
    const modalSubtitle = document.getElementById("policyEnforcementModalSubtitle");

    if (!modal || !modalClose) return;

    function setText(id, value) {
      const el = document.getElementById(id);
      if (!el) return;
      el.textContent = (value === null || value === undefined || value === "") ? "—" : String(value);
    }

    function setHtml(id, html) {
      const el = document.getElementById(id);
      if (!el) return;
      el.innerHTML = html;
    }

    function parseJsonArray(value) {
      if (value === null || value === undefined || value === "") return [];
      if (Array.isArray(value)) return value;
      try {
        const parsed = JSON.parse(value);
        return Array.isArray(parsed) ? parsed : [];
      } catch (_) {
        return [];
      }
    }

    function parseJsonObject(value) {
      if (value === null || value === undefined || value === "") return null;
      if (typeof value === "object") return value;
      try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === "object" ? parsed : null;
      } catch (_) {
        return null;
      }
    }

    function formatBoolTranscode(value) {
      return Number(value || 0) === 1 ? label("yes", "Yes") : label("no", "No");
    }

    function buildTargetMediaLabel(target) {
      if (!target) return "—";

      const mediaType = target.media_type || "—";
      const title = target.title || "";
      const gp = target.grandparent_title || "";
      const parent = target.parent_title || "";

      const parts = [];
      if (mediaType) parts.push(mediaType);
      if (title) parts.push(title);
      if (gp) parts.push(label("mediaShow", "Show") + `: ${gp}`);
      if (parent) parts.push(label("mediaParent", "Parent") + `: ${parent}`);

      return parts.length ? parts.join(" • ") : "—";
    }

    function renderSessionsSnapshot(id, details) {
      const el = document.getElementById(id);
      if (!el) return;

      const sessions = Array.isArray(details?.all_sessions) ? details.all_sessions : [];
      if (!sessions.length) {
        el.innerHTML = '<div class="text-sm text-slate-400">—</div>';
        return;
      }

      const html = sessions.map((sess, index) => {
        const media = escapeHtml(buildTargetMediaLabel(sess));
        const server = escapeHtml(sess.server_id ?? "—");
        const provider = escapeHtml(sess.provider ?? "—");
        const sessionKey = escapeHtml(sess.session_key ?? "—");
        const ip = escapeHtml(sess.ip ?? "—");
		const startedAt = escapeHtml(vodumFormatDateTime(sess.started_at ?? "—"));
		const lastSeenAt = escapeHtml(vodumFormatDateTime(sess.last_seen_at ?? "—"));
        const device = escapeHtml(sess.device ?? "—");
        const clientName = escapeHtml(sess.client_name ?? "—");
        const clientProduct = escapeHtml(sess.client_product ?? "—");
        const bitrate = escapeHtml(sess.bitrate ?? "—");
        const transcode = escapeHtml(formatBoolTranscode(sess.is_transcode));

        return `
          <div class="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
            <div class="flex items-center justify-between gap-3">
              <div class="text-sm font-medium text-white">${escapeHtml(label("session", "Session"))} ${index + 1}</div>
              <div class="text-xs text-slate-400">session_key: ${sessionKey}</div>
            </div>
            <div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("serverProvider", "Server / provider"))}</div><div class="mt-1 text-sm text-slate-100">${server} / ${provider}</div></div>
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">IP</div><div class="mt-1 text-sm text-slate-100">${ip}</div></div>
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("device", "Device"))}</div><div class="mt-1 text-sm text-slate-100">${device}</div></div>
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("client", "Client"))}</div><div class="mt-1 text-sm text-slate-100">${clientName} / ${clientProduct}</div></div>
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("startedAt", "Started at"))}</div><div class="mt-1 text-sm text-slate-100">${startedAt}</div></div>
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("lastSeenAt", "Last seen at"))}</div><div class="mt-1 text-sm text-slate-100">${lastSeenAt}</div></div>
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("bitrate", "Bitrate"))}</div><div class="mt-1 text-sm text-slate-100">${bitrate}</div></div>
              <div><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("transcode", "Transcode"))}</div><div class="mt-1 text-sm text-slate-100">${transcode}</div></div>
              <div class="md:col-span-2 xl:col-span-3"><div class="text-[11px] uppercase tracking-wide text-slate-500">${escapeHtml(label("media", "Media"))}</div><div class="mt-1 text-sm text-slate-100 break-words">${media}</div></div>
            </div>
          </div>
        `;
      }).join("");

      el.innerHTML = html;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function renderIpBadges(id, value) {
      const ips = parseJsonArray(value);
      if (!ips.length) {
        setHtml(id, '<span class="text-sm text-slate-400">—</span>');
        return;
      }

      const html = ips.map((ip) => `
        <span class="inline-flex items-center rounded-full border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs text-slate-200">
          ${escapeHtml(ip)}
        </span>
      `).join("");

      setHtml(id, html);
    }

    function formatRuleValueJson(value) {
      if (value === null || value === undefined || value === "") return "—";
      if (typeof value !== "string") {
        try {
          return JSON.stringify(value, null, 2);
        } catch (_) {
          return String(value);
        }
      }

      try {
        return JSON.stringify(JSON.parse(value), null, 2);
      } catch (_) {
        return value;
      }
    }

    function openModal(data) {
      const details = parseJsonObject(data.details_json);
      const target = details?.target_session || null;

      setText("pem_enforcement_id", data.enforcement_id);
      setText("pem_created_at", vodumFormatDateTime(data.created_at));
      setText("pem_action", data.action);
      setText("pem_user_label", data.user_label);
      setText("pem_account_username", data.account_username);
      setText("pem_vodum_username", data.vodum_username);
      setText("pem_vodum_user_id", data.vodum_user_id);
      setText("pem_external_user_id", data.external_user_id);
      renderIpBadges("pem_ips_involved", data.ips_json);

      setText("pem_target_ip", target?.ip);
      setText("pem_target_device", target?.device);
      setText("pem_target_client", [target?.client_name, target?.client_product].filter(Boolean).join(" / "));
      setText("pem_target_media", buildTargetMediaLabel(target));
	  setText("pem_target_started_at", vodumFormatDateTime(target?.started_at));
      setText("pem_target_last_seen_at", vodumFormatDateTime(target?.last_seen_at));
      setText("pem_target_bitrate", target?.bitrate);
      setText("pem_target_transcode", formatBoolTranscode(target?.is_transcode));
      setText("pem_session_count", details?.session_count);

      renderSessionsSnapshot("pem_sessions_snapshot", details);
      setText("pem_details_json", formatRuleValueJson(data.details_json));

      setText("pem_rule_type", data.rule_type);
      setText("pem_provider", data.provider);
      setText("pem_server_name", data.server_name);
      setText("pem_policy_id", data.policy_id);
      setText("pem_scope", `${data.scope_type || "—"} / ${data.scope_id ?? "—"}`);
      setText("pem_policy_priority", data.policy_priority);
      setText("pem_reason", data.reason);
      setText("pem_session_key", data.session_key);
      setText("pem_rule_value_json", formatRuleValueJson(data.rule_value_json));

      modalSubtitle.textContent = `${data.rule_type || "—"} • ${data.server_name || "—"} • ${vodumFormatDateTime(data.created_at)}`;

      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
      document.body.classList.add("overflow-hidden");
    }

    function closeModal() {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("overflow-hidden");
    }

    const viewToggleBtn = document.getElementById("policyEnforcementViewToggleBtn");
    const eventView = document.getElementById("policyEnforcementEventView");
    const groupView = document.getElementById("policyEnforcementGroupView");
    const tableTitle = document.getElementById("policyEnforcementTableTitle");

    const groupModal = document.getElementById("policyEnforcementGroupModal");
    const groupModalClose = document.getElementById("policyEnforcementGroupModalClose");
    const groupModalTitle = document.getElementById("policyEnforcementGroupModalTitle");
    const groupModalSubtitle = document.getElementById("policyEnforcementGroupModalSubtitle");
    const groupModalRows = document.getElementById("policyEnforcementGroupModalRows");

    function setEnforcementViewMode(mode) {
      const grouped = mode === "group";

      if (eventView) eventView.classList.toggle("hidden", grouped);
      if (groupView) groupView.classList.toggle("hidden", !grouped);

      if (tableTitle) {
        tableTitle.textContent = grouped ? label("groupedEnforcements", "Grouped enforcements") : label("recentEnforcements", "Recent enforcements");
      }

      if (viewToggleBtn) {
        viewToggleBtn.textContent = grouped ? label("eventView", "Event view") : label("groupByUser", "Group by user");
        viewToggleBtn.dataset.nextMode = grouped ? "event" : "group";
      }

      try {
        localStorage.setItem("vodum_policy_enforcement_view", grouped ? "group" : "event");
      } catch (_) {}
    }

    function closeGroupModal() {
      if (!groupModal) return;
      groupModal.classList.add("hidden");
      groupModal.setAttribute("aria-hidden", "true");
      document.body.classList.remove("overflow-hidden");
    }

    function openGroupModal(groupData) {
      if (!groupModal || !groupModalRows) return;

      const actorKey = groupData.actor_key || "";
      const userLabel = groupData.user_label || "—";

      groupModalTitle.textContent = label("userHistory", "User history") + ": " + userLabel;
      groupModalSubtitle.textContent = label("last24h", "Last 24h");

      groupModalRows.innerHTML = `
        <tr>
          <td class="p-4 text-slate-400" colspan="6">${escapeHtml(label("loading", "Loading..."))}</td>
        </tr>
      `;

      groupModal.classList.remove("hidden");
      groupModal.setAttribute("aria-hidden", "false");
      document.body.classList.add("overflow-hidden");

      fetch(`/monitoring/policies/enforcements/by-user?actor_key=${encodeURIComponent(actorKey)}`)
        .then((response) => response.json())
        .then((payload) => {
          const rows = Array.isArray(payload.rows) ? payload.rows : [];

          if (!rows.length) {
            groupModalRows.innerHTML = `
              <tr>
                <td class="p-4 text-slate-400" colspan="6">${escapeHtml(label("noUserHistory24h", "No history in the last 24h."))}</td>
              </tr>
            `;
            return;
          }

          groupModalRows.innerHTML = "";

          rows.forEach((item) => {
            const tr = document.createElement("tr");
            tr.className = "border-t border-slate-800 cursor-pointer hover:bg-slate-800/40";
            tr.tabIndex = 0;
            tr.setAttribute("role", "button");

            const actionBadge = item.action === "kill"
              ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full bg-rose-950/40 border border-rose-800 text-[11px] text-rose-300">${escapeHtml(label("killAction", "Kill"))}</span>'
              : '<span class="inline-flex items-center px-2 py-0.5 rounded-full bg-amber-950/40 border border-amber-800 text-[11px] text-amber-300">${escapeHtml(label("warnAction", "Warn"))}</span>';

            tr.innerHTML = `
              <td class="p-3 text-slate-300">${escapeHtml(vodumFormatDateTime(item.created_at))}</td>
              <td class="p-3 text-slate-300">${escapeHtml(item.rule_type || "—")}</td>
              <td class="p-3 text-slate-400">${escapeHtml(item.provider || "—")}</td>
              <td class="p-3 text-slate-400">${escapeHtml(item.server_name || "—")}</td>
              <td class="p-3">${actionBadge}</td>
              <td class="p-3 text-slate-400">${escapeHtml(item.reason || "—")}</td>
            `;

            tr.addEventListener("click", () => {
              closeGroupModal();
              openModal(item);
            });

            tr.addEventListener("keydown", (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                closeGroupModal();
                openModal(item);
              }
            });

            groupModalRows.appendChild(tr);
          });
        })
        .catch(() => {
          groupModalRows.innerHTML = `
            <tr>
              <td class="p-4 text-rose-300" colspan="6">${escapeHtml(label("unableUserHistory", "Unable to load user history."))}</td>
            </tr>
          `;
        });
    }

    if (viewToggleBtn && viewToggleBtn.dataset.boundPolicyViewToggle !== "1") {
      viewToggleBtn.dataset.boundPolicyViewToggle = "1";

      viewToggleBtn.addEventListener("click", () => {
        const currentMode = localStorage.getItem("vodum_policy_enforcement_view") || "event";
        const nextMode = currentMode === "group" ? "event" : "group";
        setEnforcementViewMode(nextMode);
      });
    }

    try {
      setEnforcementViewMode(localStorage.getItem("vodum_policy_enforcement_view") || "event");
    } catch (_) {
      setEnforcementViewMode("event");
    }

    root.querySelectorAll('tr[data-enforcement-group]').forEach((row) => {
      if (row.dataset.boundPolicyGroupModal === "1") return;
      row.dataset.boundPolicyGroupModal = "1";

      row.addEventListener("click", () => {
        try {
          openGroupModal(JSON.parse(row.getAttribute("data-enforcement-group")));
        } catch (_) {}
      });

      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          try {
            openGroupModal(JSON.parse(row.getAttribute("data-enforcement-group")));
          } catch (_) {}
        }
      });
    });

    if (groupModalClose && groupModalClose.dataset.boundPolicyGroupClose !== "1") {
      groupModalClose.dataset.boundPolicyGroupClose = "1";
      groupModalClose.addEventListener("click", closeGroupModal);
    }

    if (groupModal && groupModal.dataset.boundPolicyGroupBackdrop !== "1") {
      groupModal.dataset.boundPolicyGroupBackdrop = "1";
      groupModal.addEventListener("click", (e) => {
        if (e.target === groupModal || (e.target.classList && e.target.classList.contains("bg-black/70"))) {
          closeGroupModal();
        }
      });
    }

    root.querySelectorAll('tr[data-enforcement]').forEach((row) => {
      if (row.dataset.boundPolicyModal === "1") return;
      row.dataset.boundPolicyModal = "1";

      row.addEventListener("click", () => {
        try {
          const payload = JSON.parse(row.getAttribute("data-enforcement"));
          openModal(payload);
        } catch (_) {}
      });

      row.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          try {
            const payload = JSON.parse(row.getAttribute("data-enforcement"));
            openModal(payload);
          } catch (_) {}
        }
      });
    });

    if (modalClose.dataset.boundPolicyClose !== "1") {
      modalClose.dataset.boundPolicyClose = "1";
      modalClose.addEventListener("click", closeModal);
    }

    if (modal.dataset.boundPolicyBackdrop !== "1") {
      modal.dataset.boundPolicyBackdrop = "1";
      modal.addEventListener("click", (e) => {
        if (e.target === modal || (e.target.classList && e.target.classList.contains("bg-black/70"))) {
          closeModal();
        }
      });
    }

    if (document.body.dataset.boundPolicyEscape !== "1") {
      document.body.dataset.boundPolicyEscape = "1";
      document.addEventListener("keydown", (e) => {
        if (e.key !== "Escape") return;

        const currentGroupModal = document.getElementById("policyEnforcementGroupModal");
        if (currentGroupModal && !currentGroupModal.classList.contains("hidden")) {
          currentGroupModal.classList.add("hidden");
          currentGroupModal.setAttribute("aria-hidden", "true");
          document.body.classList.remove("overflow-hidden");
          return;
        }

        const currentModal = document.getElementById("policyEnforcementModal");
        if (currentModal && !currentModal.classList.contains("hidden")) {
          currentModal.classList.add("hidden");
          currentModal.setAttribute("aria-hidden", "true");
          document.body.classList.remove("overflow-hidden");
        }
      });
    }
  }

  function initPoliciesTab() {
    buildPoliciesCharts();
    bindPolicyEnforcementRows();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPoliciesTab, { once: true });
  } else {
    initPoliciesTab();
  }

  document.addEventListener("htmx:load", initPoliciesTab);
})();
