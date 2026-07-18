(function () {
  const configElement = document.getElementById("subscription-template-editor-config");
  if (!configElement) return;
  let CONFIG = {};
  try { CONFIG = JSON.parse(configElement.textContent || "{}"); }
  catch (error) { console.error("Invalid subscription template editor configuration", error); return; }
  const t = (key) => CONFIG.labels?.[key] || key;
  let TEMPLATE_POLICIES = [];
  let EDIT_INDEX = null;

  const SIMPLE_RULE_TYPES = ["max_streams_per_user", "max_ips_per_user", "max_bitrate_kbps", "device_allowlist"];

  function isTemplateAdvancedMode() {
    const advancedBox = document.getElementById("advanced_policy_editor");
    return !!advancedBox && !advancedBox.classList.contains("hidden");
  }

  function syncPoliciesJson() {
    if (!isTemplateAdvancedMode()) {
      syncSimpleRulesToPolicies();
    }
    document.getElementById("policies_json").value = JSON.stringify(TEMPLATE_POLICIES || []);
    return true;
  }

  function setTemplatePolicyMode(mode) {
    const simpleBox = document.getElementById("simple_policy_mode");
    const summaryBox = document.getElementById("simple_policy_summary");
    const advancedBox = document.getElementById("advanced_policy_editor");
    if (!simpleBox || !summaryBox || !advancedBox) return;

    const advanced = mode === "advanced";

    if (advanced) {
      syncSimpleRulesToPolicies();
      renderPoliciesTable();
    } else {
      hydrateSimpleRulesFromPolicies();
      renderPolicyCards();
    }

    simpleBox.classList.toggle("hidden", advanced);
    summaryBox.classList.toggle("hidden", advanced);
    advancedBox.classList.toggle("hidden", !advanced);
    document.getElementById("policies_json").value = JSON.stringify(TEMPLATE_POLICIES || []);
  }

  function toggleAdvancedPolicyEditor() {
    setTemplatePolicyMode("advanced");
  }

  function updateTemplateSubmitButton() {
    const btn = document.getElementById("tpl_submit_btn");
    const templateId = document.getElementById("template_id").value;
    if (!btn) return;
    btn.textContent = templateId ? t("save") : t("create");
  }

  function updatePolicyActionButton() {
    const btn = document.getElementById("p_add_btn");
    if (!btn) return;
    btn.textContent = EDIT_INDEX !== null
      ? t("save")
      : t("subscription_templates_add_policy");
  }

  function resetPolicyBuilder() {
    EDIT_INDEX = null;
    document.getElementById("p_rule_type").value = "max_streams_per_user";
    document.getElementById("p_provider").value = "";
    document.getElementById("p_server_id").value = "";
    document.getElementById("p_priority").value = "100";
    document.getElementById("p_enabled").value = "1";
    document.getElementById("p_max_value").value = "";
    document.getElementById("p_allow_local_ip").checked = false;
    document.getElementById("p_max_kbps").value = "";
    document.getElementById("p_allowed_devices").value = "";
    document.getElementById("p_warn_title").value = t("policies_warn_title_default");
    document.getElementById("p_warn_text").value = t("policies_warn_text_default");
    document.getElementById("p_selector").value = "kill_newest";
    updatePolicyActionButton();
  }

  function resetSimpleRules() {
    document.getElementById("simple_streams_enabled").checked = false;
    document.getElementById("simple_streams_max").value = "2";
    document.getElementById("simple_streams_selector").value = "kill_newest";
    document.getElementById("simple_streams_lan").checked = false;

    document.getElementById("simple_ips_enabled").checked = false;
    document.getElementById("simple_ips_max").value = "1";
    document.getElementById("simple_ips_selector").value = "kill_newest";
    document.getElementById("simple_ips_lan").checked = false;

    document.getElementById("simple_bitrate_enabled").checked = false;
    document.getElementById("simple_bitrate_max").value = "20000";

    document.getElementById("simple_devices_enabled").checked = false;
    document.getElementById("simple_devices_allowed").value = "";
  }

  function updateLifetimeDurationState() {
    const lifetime = document.getElementById("tpl_is_lifetime");
    const duration = document.getElementById("tpl_duration_days");

    if (!lifetime || !duration) return;

    if (lifetime.checked) {
      duration.dataset.previousValue = duration.value || "30";
      duration.value = "";
      duration.disabled = true;
      duration.placeholder = t("lifetime_subscription");
      duration.classList.add("opacity-50", "cursor-not-allowed");
    } else {
      duration.disabled = false;
      duration.placeholder = "30";
      duration.classList.remove("opacity-50", "cursor-not-allowed");

      if (!duration.value) {
        duration.value = duration.dataset.previousValue || "30";
      }
    }
  }

  function resetTemplateEditor() {
    document.getElementById("template_id").value = "";
    document.getElementById("tpl_name").value = "";
    document.getElementById("tpl_notes").value = "";
    document.getElementById("tpl_duration_days").value = "30";
    document.getElementById("tpl_subscription_value").value = "0";
    document.getElementById("tpl_is_default").checked = false;
    document.getElementById("tpl_is_enabled").checked = true;
    document.getElementById("tpl_is_lifetime").checked = false;
    updateLifetimeDurationState();
    TEMPLATE_POLICIES = [];
    EDIT_INDEX = null;
    resetSimpleRules();
    syncPoliciesJson();
    renderPoliciesTable();
    resetPolicyBuilder();
    updateTemplateSubmitButton();
    setTemplatePolicyMode("simple");
  }

  function getDefaultRule() {
    return {
      selector: "kill_newest",
      warn_title: t("policies_warn_title_default"),
      warn_text: t("policies_warn_text_default")
    };
  }

  function isSimpleManagedPolicy(p) {
    if (!p || !SIMPLE_RULE_TYPES.includes(p.rule_type)) return false;
    const hasProvider = !!p.provider;
    const hasServer = !!p.server_id;
    const priority = parseInt(p.priority ?? 100, 10) || 100;
    return !hasProvider && !hasServer && priority === 100;
  }

  function findSimplePolicyIndex(ruleType) {
    return TEMPLATE_POLICIES.findIndex((p) => p.rule_type === ruleType && isSimpleManagedPolicy(p));
  }

  function upsertSimplePolicy(ruleType, rule) {
    const policy = {
      rule_type: ruleType,
      provider: null,
      server_id: null,
      priority: 100,
      is_enabled: 1,
      rule: rule
    };

    const idx = findSimplePolicyIndex(ruleType);
    if (idx >= 0) {
      TEMPLATE_POLICIES[idx] = policy;
    } else {
      TEMPLATE_POLICIES.push(policy);
    }
  }

  function removeSimplePolicy(ruleType) {
    TEMPLATE_POLICIES = TEMPLATE_POLICIES.filter((p) => !(p.rule_type === ruleType && isSimpleManagedPolicy(p)));
  }

  function syncSimpleRulesToPolicies() {
    const baseStreamsRule = getDefaultRule();
    baseStreamsRule.max = parseInt(document.getElementById("simple_streams_max").value || "2", 10) || 2;
    baseStreamsRule.selector = document.getElementById("simple_streams_selector").value || "kill_newest";
    baseStreamsRule.allow_local_ip = !!document.getElementById("simple_streams_lan").checked;
    if (document.getElementById("simple_streams_enabled").checked) {
      upsertSimplePolicy("max_streams_per_user", baseStreamsRule);
    } else {
      removeSimplePolicy("max_streams_per_user");
    }

    const baseIpsRule = getDefaultRule();
    baseIpsRule.max = parseInt(document.getElementById("simple_ips_max").value || "1", 10) || 1;
    baseIpsRule.selector = document.getElementById("simple_ips_selector").value || "kill_newest";
    baseIpsRule.allow_local_ip = !!document.getElementById("simple_ips_lan").checked;
    if (document.getElementById("simple_ips_enabled").checked) {
      upsertSimplePolicy("max_ips_per_user", baseIpsRule);
    } else {
      removeSimplePolicy("max_ips_per_user");
    }

    const bitrateRule = getDefaultRule();
    bitrateRule.max_kbps = parseInt(document.getElementById("simple_bitrate_max").value || "20000", 10) || 20000;
    if (document.getElementById("simple_bitrate_enabled").checked) {
      upsertSimplePolicy("max_bitrate_kbps", bitrateRule);
    } else {
      removeSimplePolicy("max_bitrate_kbps");
    }

    const devicesRule = getDefaultRule();
    devicesRule.allowed = (document.getElementById("simple_devices_allowed").value || "")
      .split(",")
      .map(s => s.trim())
      .filter(Boolean);
    if (document.getElementById("simple_devices_enabled").checked && devicesRule.allowed.length) {
      upsertSimplePolicy("device_allowlist", devicesRule);
    } else {
      removeSimplePolicy("device_allowlist");
    }

    renderPoliciesTable();
  }

  function hydrateSimpleRulesFromPolicies() {
    resetSimpleRules();

    const streams = TEMPLATE_POLICIES[findSimplePolicyIndex("max_streams_per_user")];
    if (streams) {
      document.getElementById("simple_streams_enabled").checked = true;
      document.getElementById("simple_streams_max").value = streams.rule?.max ?? "2";
      document.getElementById("simple_streams_selector").value = streams.rule?.selector || "kill_newest";
      document.getElementById("simple_streams_lan").checked = !!streams.rule?.allow_local_ip;
    }

    const ips = TEMPLATE_POLICIES[findSimplePolicyIndex("max_ips_per_user")];
    if (ips) {
      document.getElementById("simple_ips_enabled").checked = true;
      document.getElementById("simple_ips_max").value = ips.rule?.max ?? "1";
      document.getElementById("simple_ips_selector").value = ips.rule?.selector || "kill_newest";
      document.getElementById("simple_ips_lan").checked = !!ips.rule?.allow_local_ip;
    }

    const bitrate = TEMPLATE_POLICIES[findSimplePolicyIndex("max_bitrate_kbps")];
    if (bitrate) {
      document.getElementById("simple_bitrate_enabled").checked = true;
      document.getElementById("simple_bitrate_max").value = bitrate.rule?.max_kbps ?? "20000";
    }

    const devices = TEMPLATE_POLICIES[findSimplePolicyIndex("device_allowlist")];
    if (devices) {
      document.getElementById("simple_devices_enabled").checked = true;
      document.getElementById("simple_devices_allowed").value = (devices.rule?.allowed || []).join(", ");
    }
  }

  function getPolicyFromBuilder() {
    const rule_type = document.getElementById("p_rule_type").value;
    const provider = document.getElementById("p_provider").value;
    const server_id = document.getElementById("p_server_id").value;
    const priority = document.getElementById("p_priority").value || "100";
    const is_enabled = document.getElementById("p_enabled").value;

    const selector = document.getElementById("p_selector").value;
    const warn_title = document.getElementById("p_warn_title").value || t("policies_warn_title_default");
    const warn_text = document.getElementById("p_warn_text").value || t("policies_warn_text_default");

    const max_value = document.getElementById("p_max_value").value;
    const allow_local_ip = document.getElementById("p_allow_local_ip").checked;

    const max_kbps = document.getElementById("p_max_kbps").value;
    const allowed_devices = document.getElementById("p_allowed_devices").value;

    const rule = { selector, warn_title, warn_text };

    if (["max_streams_per_user","max_streams_per_ip","max_ips_per_user","max_transcodes_global"].includes(rule_type)) {
      const mv = parseInt(max_value || "1", 10);
      rule.max = isNaN(mv) ? 1 : mv;
    }
    if (["max_streams_per_user","max_streams_per_ip","max_ips_per_user"].includes(rule_type)) {
      rule.allow_local_ip = !!allow_local_ip;
    }
    if (rule_type === "max_bitrate_kbps") {
      const mk = parseInt(max_kbps || "20000", 10);
      rule.max_kbps = isNaN(mk) ? 20000 : mk;
    }
    if (rule_type === "device_allowlist") {
      const list = (allowed_devices || "").split(",").map(s => s.trim()).filter(Boolean);
      rule.allowed = list;
    }

    return {
      rule_type,
      provider: provider || null,
      server_id: server_id || null,
      priority: parseInt(priority, 10) || 100,
      is_enabled: is_enabled === "1" ? 1 : 0,
      rule
    };
  }

  function addPolicyToTemplate() {
    const p = getPolicyFromBuilder();
    if (!p.rule_type) return;

    if (EDIT_INDEX !== null) {
      TEMPLATE_POLICIES[EDIT_INDEX] = p;
    } else {
      TEMPLATE_POLICIES.push(p);
    }

    EDIT_INDEX = null;
    hydrateSimpleRulesFromPolicies();
    renderPoliciesTable();
    syncPoliciesJson();
    resetPolicyBuilder();
  }

  function editPolicy(i) {
    const p = TEMPLATE_POLICIES[i];
    if (!p) return;
    EDIT_INDEX = i;

    setTemplatePolicyMode("advanced");
    document.getElementById("p_rule_type").value = p.rule_type;
    document.getElementById("p_provider").value = p.provider || "";
    document.getElementById("p_server_id").value = p.server_id || "";
    document.getElementById("p_priority").value = p.priority || 100;
    document.getElementById("p_enabled").value = String(p.is_enabled ?? 1);

    const rule = p.rule || {};
    document.getElementById("p_selector").value = rule.selector || "kill_newest";
    document.getElementById("p_warn_title").value = rule.warn_title || t("policies_warn_title_default");
    document.getElementById("p_warn_text").value = rule.warn_text || t("policies_warn_text_default");

    document.getElementById("p_max_value").value = rule.max ?? "";
    document.getElementById("p_allow_local_ip").checked = !!rule.allow_local_ip;
    document.getElementById("p_max_kbps").value = rule.max_kbps ?? "";
    document.getElementById("p_allowed_devices").value = (rule.allowed || []).join(", ");

    updatePolicyActionButton();
    document.getElementById("advanced_policy_editor").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function deletePolicy(i) {
    TEMPLATE_POLICIES.splice(i, 1);
    EDIT_INDEX = null;
    hydrateSimpleRulesFromPolicies();
    renderPoliciesTable();
    syncPoliciesJson();
    updatePolicyActionButton();
  }

  function getRuleTypeLabel(ruleType) {
    const labels = {
      "max_streams_per_user": t("policies_rule_max_streams_user"),
      "max_ips_per_user": t("policies_rule_max_ips_user"),
      "max_streams_per_ip": t("policies_rule_max_streams_ip"),
      "max_transcodes_global": t("policies_rule_max_transcodes_server"),
      "ban_4k_transcode": t("policies_rule_ban_4k_transcode"),
      "max_bitrate_kbps": t("policies_rule_max_bitrate"),
      "device_allowlist": t("policies_rule_device_allowlist")
    };
    return labels[ruleType] || ruleType || "-";
  }

  function getProviderLabel(provider) {
    if (provider === "plex") return t("policies_provider_plex");
    if (provider === "jellyfin") return t("policies_provider_jellyfin");
    return t("policies_provider_both");
  }

  function getServerLabel(serverId) {
    if (!serverId) return t("policies_all_servers");
    const option = document.querySelector(`#p_server_id option[value="${serverId}"]`);
    return option ? option.textContent : `#${serverId}`;
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function getPolicyDetails(p) {
    const rule = p.rule || {};
    const parts = [];

    if (rule.max !== undefined && rule.max !== null && rule.max !== "") parts.push(`max=${rule.max}`);
    if (rule.max_kbps !== undefined && rule.max_kbps !== null && rule.max_kbps !== "") parts.push(`max_kbps=${rule.max_kbps}`);
    if (Array.isArray(rule.allowed) && rule.allowed.length) parts.push(`allowed=${rule.allowed.join(", ")}`);
    if (rule.allow_local_ip) parts.push(t("lan"));
    if (rule.selector) parts.push(`selector=${rule.selector}`);

    return parts.length ? parts.join(" • ") : "—";
  }

  function getPolicySummaryTitle(p) {
    const rule = p.rule || {};
    if (p.rule_type === "max_streams_per_user") return `${rule.max ?? "?"} ${t("subscription_summary_streams_per_user")}`;
    if (p.rule_type === "max_ips_per_user") return `${rule.max ?? "?"} ${t("subscription_summary_ips_per_user")}`;
    if (p.rule_type === "max_streams_per_ip") return `${rule.max ?? "?"} ${t("subscription_summary_streams_per_ip")}`;
    if (p.rule_type === "max_transcodes_global") return `${rule.max ?? "?"} ${t("subscription_summary_server_transcodes")}`;
    if (p.rule_type === "max_bitrate_kbps") return `${rule.max_kbps ?? "?"} ${t("subscription_summary_kbps_max_bitrate")}`;
    if (p.rule_type === "device_allowlist") return `${t("subscription_allowed_devices")}`;
    if (p.rule_type === "ban_4k_transcode") return `${t("subscription_summary_4k_transcode_blocked")}`;
    return getRuleTypeLabel(p.rule_type);
  }

  function renderPolicyCards() {
    const box = document.getElementById("tpl_policy_cards");
    if (!box) return;

    if (!TEMPLATE_POLICIES.length) {
      box.innerHTML = `
        <div class="md:col-span-2 xl:col-span-3 rounded-xl border border-dashed border-slate-700 bg-slate-900/30 px-4 py-5 text-sm text-slate-400">
          ${t("subscription_no_rules_hint")}
        </div>
      `;
      return;
    }

    box.innerHTML = TEMPLATE_POLICIES.map((p, i) => {
      const enabled = p.is_enabled ? t("enabled") : t("disabled");
      const enabledClass = p.is_enabled ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : "border-slate-700 bg-slate-800 text-slate-400";
      const origin = isSimpleManagedPolicy(p) ? t("simple") : t("advanced");
      const originClass = isSimpleManagedPolicy(p) ? "border-indigo-500/30 bg-indigo-500/10 text-indigo-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300";

      return `
        <div class="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <div class="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-3">
            <div class="min-w-0">
              <div class="text-sm font-semibold text-slate-100">${escapeHtml(getPolicySummaryTitle(p))}</div>
              <div class="text-xs text-slate-500 mt-1">${escapeHtml(getRuleTypeLabel(p.rule_type))}</div>
            </div>
            <div class="flex gap-1 shrink-0">
              <span class="text-[10px] px-2 py-0.5 rounded-full border ${enabledClass}">${enabled}</span>
              <span class="text-[10px] px-2 py-0.5 rounded-full border ${originClass}">${origin}</span>
            </div>
          </div>
          <div class="mt-3 text-xs text-slate-400 leading-5">
            <div>${escapeHtml(getProviderLabel(p.provider))} • ${escapeHtml(getServerLabel(p.server_id))}</div>
            <div>${escapeHtml(getPolicyDetails(p))}</div>
          </div>
          <div class="mt-3 flex gap-3 text-xs">
            <button type="button" class="text-indigo-300 hover:text-indigo-200" onclick="editPolicy(${i})">${t("edit")}</button>
            <button type="button" class="text-rose-300 hover:text-rose-200" onclick="deletePolicy(${i})">${t("delete")}</button>
          </div>
        </div>
      `;
    }).join("");
  }

  function renderPoliciesTable() {
    const tbody = document.getElementById("tpl_policies_table");
    const badge = document.getElementById("tpl_policies_count_badge");

    if (badge) {
      badge.textContent = `${TEMPLATE_POLICIES.length} ${t("policies")}`;
      badge.classList.toggle("hidden", TEMPLATE_POLICIES.length === 0);
    }

    renderPolicyCards();

    if (!tbody) return;

    if (!TEMPLATE_POLICIES.length) {
      tbody.innerHTML = `<tr><td class="px-4 py-3 text-slate-500" colspan="7">${t("subscription_templates_no_policies")}</td></tr>`;
      return;
    }

    tbody.innerHTML = TEMPLATE_POLICIES.map((p, i) => {
      const enabled = p.is_enabled ? t("enabled") : t("disabled");
      const enabledClass = p.is_enabled ? "text-emerald-300" : "text-slate-500";

      return `
        <tr class="border-t border-slate-800 align-top">
          <td class="px-4 py-3">
            <div class="flex flex-col gap-1">
              <button type="button" class="text-left text-slate-300 hover:text-white" onclick="editPolicy(${i})">${t("edit")}</button>
              <button type="button" class="text-left text-rose-300 hover:text-rose-200" onclick="deletePolicy(${i})">${t("delete")}</button>
            </div>
          </td>
          <td class="px-4 py-3 text-slate-200">${escapeHtml(getRuleTypeLabel(p.rule_type))}</td>
          <td class="px-4 py-3 text-slate-400">${escapeHtml(getProviderLabel(p.provider))}</td>
          <td class="px-4 py-3 text-slate-400">${escapeHtml(getServerLabel(p.server_id))}</td>
          <td class="px-4 py-3 text-slate-400">${escapeHtml(p.priority ?? 100)}</td>
          <td class="px-4 py-3 ${enabledClass}">${escapeHtml(enabled)}</td>
          <td class="px-4 py-3 text-slate-400">${escapeHtml(getPolicyDetails(p))}</td>
        </tr>
      `;
    }).join("");
  }

  function loadTemplateForEdit(tpl) {
    document.getElementById("template_id").value = tpl.id;
    document.getElementById("tpl_name").value = tpl.name || "";
    document.getElementById("tpl_notes").value = tpl.notes || "";
    document.getElementById("tpl_duration_days").value = tpl.duration_days || 30;
    document.getElementById("tpl_subscription_value").value = tpl.subscription_value || 0;
    document.getElementById("tpl_is_default").checked = String(tpl.is_default || "0") === "1";
    document.getElementById("tpl_is_enabled").checked = String(tpl.is_enabled ?? 1) === "1";
    document.getElementById("tpl_is_lifetime").checked = String(tpl.is_lifetime || "0") === "1";
    updateLifetimeDurationState();

    TEMPLATE_POLICIES = [];
    try {
      TEMPLATE_POLICIES = JSON.parse(tpl.policies_json || "[]") || [];
    } catch (e) {
      TEMPLATE_POLICIES = [];
    }

    hydrateSimpleRulesFromPolicies();
    renderPoliciesTable();
    syncPoliciesJson();
    resetPolicyBuilder();
    updateTemplateSubmitButton();
    setTemplatePolicyMode("simple");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  document.addEventListener("DOMContentLoaded", () => {
    [
      "simple_streams_enabled", "simple_streams_max", "simple_streams_selector", "simple_streams_lan",
      "simple_ips_enabled", "simple_ips_max", "simple_ips_selector", "simple_ips_lan",
      "simple_bitrate_enabled", "simple_bitrate_max",
      "simple_devices_enabled", "simple_devices_allowed"
    ].forEach((id) => {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("input", () => { syncSimpleRulesToPolicies(); syncPoliciesJson(); });
      el.addEventListener("change", () => { syncSimpleRulesToPolicies(); syncPoliciesJson(); });
    });

    updateLifetimeDurationState();
    renderPoliciesTable();
    syncPoliciesJson();
    resetPolicyBuilder();
    updateTemplateSubmitButton();
  });

  Object.assign(window, { syncPoliciesJson, setTemplatePolicyMode, updateLifetimeDurationState, resetTemplateEditor, addPolicyToTemplate, resetPolicyBuilder, editPolicy, deletePolicy, loadTemplateForEdit });
})();
