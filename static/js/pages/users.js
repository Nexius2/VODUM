(function () {
  function submitWithFirstPage(form) {
    let pageInput = form.querySelector('input[name="page"]');
    if (!pageInput) {
      pageInput = document.createElement("input");
      pageInput.type = "hidden";
      pageInput.name = "page";
      form.appendChild(pageInput);
    }
    pageInput.value = "1";

    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  }

  function initUsersFilters() {
    const form = document.getElementById("users_filter_form");
    if (!form || form.dataset.vodumBound === "1") return;
    form.dataset.vodumBound = "1";

    const searchInput = form.querySelector('input[name="q"]');
    const statusCheckboxes = form.querySelectorAll('input[name="status"]');
    let timer = null;

    if (searchInput) {
      searchInput.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => submitWithFirstPage(form), 500);
      });

      searchInput.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        clearTimeout(timer);
        submitWithFirstPage(form);
      });
    }

    statusCheckboxes.forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        clearTimeout(timer);
        submitWithFirstPage(form);
      });
    });
  }

  function initReferralFilters() {
    const form = document.getElementById("referrals_filter_form");
    if (!form || form.dataset.vodumBound === "1") return;
    form.dataset.vodumBound = "1";

    form.querySelectorAll('input[name="status"]').forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        if (form.requestSubmit) form.requestSubmit();
        else form.submit();
      });
    });
  }

  function initReferralBulkActions() {
    const bulkForm = document.getElementById("referrals_bulk_form");
    if (!bulkForm || bulkForm.dataset.vodumBound === "1") return;
    bulkForm.dataset.vodumBound = "1";

    const selectAll = document.getElementById("referrals_select_all");
    const checkboxes = Array.from(bulkForm.querySelectorAll(".referral-row-checkbox"));
    const count = document.getElementById("referrals_selected_count");
    const selectedLabel = count?.dataset.selectedLabel || "selected";
    const buttons = Array.from(bulkForm.querySelectorAll("[data-bulk-action]"));
    const actions = document.getElementById("referrals_bulk_actions");

    if (!selectAll || !count) return;

    function refresh() {
      const selected = checkboxes.filter((checkbox) => checkbox.checked).length;
      count.textContent = `${selected} ${selectedLabel}`;
      buttons.forEach((button) => { button.disabled = selected === 0; });

      if (actions) {
        actions.classList.toggle("hidden", selected === 0 || buttons.length === 0);
        actions.classList.toggle("flex", selected > 0 && buttons.length > 0);
      }

      selectAll.checked = checkboxes.length > 0 && selected === checkboxes.length;
      selectAll.indeterminate = selected > 0 && selected < checkboxes.length;
    }

    selectAll.addEventListener("change", () => {
      checkboxes.forEach((checkbox) => { checkbox.checked = selectAll.checked; });
      refresh();
    });
    checkboxes.forEach((checkbox) => checkbox.addEventListener("change", refresh));
    refresh();
  }

  function initUsersPage() {
    initUsersFilters();
    initReferralFilters();
    initReferralBulkActions();
  }

  document.addEventListener("DOMContentLoaded", initUsersPage);
  document.addEventListener("htmx:load", initUsersPage);
})();

(function () {
  function cfg() {
    const node = document.getElementById("users-page-config");
    if (!node) return {};
    try { return JSON.parse(node.textContent || "{}"); }
    catch (_) { return {}; }
  }

  const config = cfg();
  const i18n = config.i18n || {};
  const api = config.api || {};
  const defaults = config.defaults || {};

  const state = {
    servers: [],
    blocks: [],
    referrerUserId: null,
    referrerUserLabel: "",
  };

  function t(key, fallback) {
    return i18n[key] || fallback || key;
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

  function el(html) {
    const template = document.createElement("template");
    template.innerHTML = html.trim();
    return template.content.firstChild;
  }

  async function fetchJSON(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
    return response.json();
  }

  function pickUrl(server) {
    const clean = (value) => {
      value = String(value || "").trim();
      if (!value || value.toLowerCase() === "none" || value.toLowerCase() === "null") return "";
      return value;
    };
    return clean(server.public_url) || clean(server.url) || clean(server.local_url) || "";
  }

  function feedback(message, kind = "info") {
    const box = document.getElementById("cu_feedback");
    if (!box) return;
    box.classList.remove("hidden");
    box.textContent = message;
    box.classList.remove("border-emerald-600", "border-red-600", "border-slate-800");
    if (kind === "success") box.classList.add("border-emerald-600");
    else if (kind === "error") box.classList.add("border-red-600");
    else box.classList.add("border-slate-800");
  }

  function computeDefaultExpirationDate(days) {
    const date = new Date();
    date.setHours(12, 0, 0, 0);
    date.setDate(date.getDate() + parseInt(days || 0, 10));
    return date.toISOString().slice(0, 10);
  }

  function applyDefaultExpirationDate(force = false) {
    const input = document.getElementById("cu_expiration");
    if (!input) return;
    if (force || !input.value) {
      input.value = computeDefaultExpirationDate(defaults.subscriptionDays || 90);
    }
  }

  function clearReferrer() {
    state.referrerUserId = null;
    state.referrerUserLabel = "";
    const input = document.getElementById("cu_referrer_user_id");
    const display = document.getElementById("cu_referrer_display");
    if (input) input.value = "";
    if (display) display.textContent = t("noReferrer", "No referrer");
  }

  function resetCreateUserForm() {
    ["cu_email", "cu_second_email", "cu_username", "cu_firstname", "cu_lastname", "cu_notes"].forEach((id) => {
      const input = document.getElementById(id);
      if (input) input.value = "";
    });

    const templateInput = document.getElementById("cu_subscription_template_id");
    if (templateInput) templateInput.value = defaults.subscriptionTemplateId || "";

    clearReferrer();
    applyDefaultExpirationDate(true);

    state.blocks = [];
    const container = document.getElementById("cu_servers_container");
    if (container) container.innerHTML = "";
    addServerBlock();
  }

  function open() {
    document.getElementById("modal_create_user")?.classList.remove("hidden");
    document.getElementById("cu_feedback")?.classList.add("hidden");
    resetCreateUserForm();
  }

  function close() {
    document.getElementById("modal_create_user")?.classList.add("hidden");
    document.getElementById("cu_feedback")?.classList.add("hidden");
  }

  function openReferrerModal() {
    document.getElementById("modal_create_user_referrer")?.classList.remove("hidden");
    const search = document.getElementById("cu_referrer_search");
    if (search) search.value = "";
    loadReferrerCandidates("");
    setTimeout(() => search?.focus(), 20);
  }

  function closeReferrerModal() {
    document.getElementById("modal_create_user_referrer")?.classList.add("hidden");
  }

  function setReferrer(user) {
    state.referrerUserId = parseInt(user.id, 10);
    state.referrerUserLabel = `${user.username || ""}${user.email ? " - " + user.email : ""}`;

    const input = document.getElementById("cu_referrer_user_id");
    const display = document.getElementById("cu_referrer_display");
    if (input) input.value = String(state.referrerUserId);
    if (display) display.textContent = state.referrerUserLabel || t("noReferrer", "No referrer");
    closeReferrerModal();
  }

  async function loadReferrerCandidates(q = "") {
    const url = api.referrers || "/api/users/referrer-candidates?q={q}";
    const rows = await fetchJSON(url.replace("{q}", encodeURIComponent(q)));
    const box = document.getElementById("cu_referrer_results");
    if (!box) return;

    const noneRow = `
      <button type="button" class="w-full text-left px-4 py-3 hover:bg-slate-800 border-b border-slate-800" data-id="" data-username="${escapeHtml(t("noReferrer", "No referrer"))}" data-email="">
        <div class="text-sm font-medium text-slate-100">${escapeHtml(t("noReferrer", "No referrer"))}</div>
        <div class="text-xs text-slate-500 mt-1">${escapeHtml(t("referrerNoneHelp", "No referrer will be attached."))}</div>
      </button>`;

    if (!rows.length) {
      box.innerHTML = noneRow + `<div class="px-4 py-3 text-sm text-slate-400">${escapeHtml(t("noUserFound", "No user found"))}</div>`;
      return;
    }

    box.innerHTML = noneRow + rows.map((user) => `
      <button type="button" class="w-full text-left px-4 py-3 hover:bg-slate-800" data-id="${user.id}" data-username="${escapeHtml(user.username || "")}" data-email="${escapeHtml(user.email || "")}">
        <div class="text-sm font-medium text-slate-100">${escapeHtml(user.username || "-")}</div>
        <div class="text-xs text-slate-400">${escapeHtml(user.email || "")}</div>
        <div class="text-xs text-slate-500 mt-1">${escapeHtml(t("referralsTotal", "Referrals"))}: ${user.referrals_count || 0}</div>
      </button>`).join("");
  }

  async function initServers() {
    state.servers = await fetchJSON(api.servers || "/api/servers");
  }

  function serverOptionsHtml() {
    const options = state.servers.map((server) => {
      const label = `${server.name} (${(server.type || "").toUpperCase()})`;
      return `<option value="${server.id}">${escapeHtml(label)}</option>`;
    });
    return `<option value="">${escapeHtml(t("chooseServer", "Choose server"))}</option>` + options.join("");
  }

  async function loadLibraries(serverId) {
    if (!serverId) return [];
    const url = api.libs || "/api/servers/{serverId}/libraries";
    return fetchJSON(url.replace("{serverId}", encodeURIComponent(serverId)));
  }

  function renderBlock(blockId) {
    const block = state.blocks.find((candidate) => candidate.id === blockId);
    if (!block) return null;

    const node = el(`
      <div class="border border-slate-800 rounded-2xl p-4 bg-slate-950">
        <div class="flex items-center justify-between mb-3">
          <div class="text-sm font-semibold">${escapeHtml(t("server", "Server"))}</div>
          <button type="button" class="text-xs px-2 py-1 rounded bg-slate-800 hover:bg-slate-700" data-action="remove">${escapeHtml(t("remove", "Remove"))}</button>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="text-xs text-slate-400">${escapeHtml(t("server", "Server"))}</label>
            <div class="flex gap-2 items-center">
              <select class="flex-1 bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm" data-field="server_id">${serverOptionsHtml()}</select>
              <button type="button" class="hidden" title="${escapeHtml(t("addLinkedPlexServers", "Add linked Plex servers"))}" data-add-linked>+</button>
            </div>
            <div class="text-xs text-slate-500 mt-1" data-server-url></div>
            <div class="text-xs text-slate-500 mt-1" data-linked-info></div>
          </div>

          <div>
            <label class="text-xs text-slate-400">${escapeHtml(t("libraries", "Libraries"))}</label>
            <div class="bg-slate-900 border border-slate-800 rounded-lg p-2 text-xs max-h-40 overflow-y-auto" data-libs>
              <div class="text-slate-500">${escapeHtml(t("selectServerFirst", "Select a server first"))}</div>
            </div>
          </div>

          <div data-jellyfin class="hidden md:col-span-2">
            <div class="text-xs text-slate-400 mb-1">${escapeHtml(t("jellyfinOptions", "Jellyfin options"))}</div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label class="text-xs text-slate-500">${escapeHtml(t("initialPasswordOptional", "Initial password optional"))}</label>
                <input type="password" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm" data-field="jellyfin_password" autocomplete="new-password">
              </div>
              <label class="flex items-center gap-2 text-sm mt-5">
                <input type="checkbox" data-field="jellyfin_force_password_change">
                <span class="text-slate-200">${escapeHtml(t("forcePasswordChange", "Force password change"))}</span>
              </label>
            </div>
          </div>

          <div data-plex class="hidden md:col-span-2">
            <div class="text-xs text-slate-400 mb-1">${escapeHtml(t("plexShareFlags", "Plex share flags"))}</div>
            <div class="flex flex-wrap gap-4 text-sm">
              <label class="flex items-center gap-2"><input type="checkbox" data-plex-flag="allowSync"><span>allowSync</span></label>
              <label class="flex items-center gap-2"><input type="checkbox" data-plex-flag="allowCameraUpload"><span>allowCameraUpload</span></label>
              <label class="flex items-center gap-2"><input type="checkbox" data-plex-flag="allowChannels"><span>allowChannels</span></label>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
              <div><label class="text-xs text-slate-500">filterMovies</label><input type="text" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm" data-plex-flag="filterMovies"></div>
              <div><label class="text-xs text-slate-500">filterTelevision</label><input type="text" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm" data-plex-flag="filterTelevision"></div>
              <div><label class="text-xs text-slate-500">filterMusic</label><input type="text" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-sm" data-plex-flag="filterMusic"></div>
            </div>

            <label class="flex items-center gap-2 text-sm mt-3"><input type="checkbox" data-field="enqueue_plex_jobs"><span class="text-slate-200">${escapeHtml(t("enqueuePlexJobs", "Enqueue Plex jobs"))}</span></label>
          </div>
        </div>
      </div>`);

    document.getElementById("cu_servers_container")?.appendChild(node);

    const select = node.querySelector('[data-field="server_id"]');
    const libsBox = node.querySelector("[data-libs]");
    const serverUrlLine = node.querySelector("[data-server-url]");
    const jellyfinBox = node.querySelector("[data-jellyfin]");
    const plexBox = node.querySelector("[data-plex]");
    const linkedInfo = node.querySelector("[data-linked-info]");
    const btnAddLinked = node.querySelector("[data-add-linked]");

    node.querySelector('[data-action="remove"]')?.addEventListener("click", () => removeServerBlock(blockId));

    select?.addEventListener("change", async () => {
      const serverId = select.value ? parseInt(select.value, 10) : null;
      block.server_id = serverId;
      block.library_ids = [];

      const server = state.servers.find((candidate) => candidate.id === serverId);
      const provider = (server?.type || "").toLowerCase();
      block.provider = provider;

      const url = server ? pickUrl(server) : "";
      if (serverUrlLine) serverUrlLine.textContent = url ? `URL: ${url}` : "";

      if (provider === "plex" && server?.linked_servers?.length) {
        if (linkedInfo) linkedInfo.textContent = `${t("linkedPlexServers", "Linked Plex servers")}: ${server.linked_servers.map((linked) => linked.name).join(", ")}`;
        if (btnAddLinked) btnAddLinked.disabled = false;
      } else {
        if (linkedInfo) linkedInfo.textContent = "";
        if (btnAddLinked) btnAddLinked.disabled = true;
      }

      jellyfinBox?.classList.toggle("hidden", provider !== "jellyfin");
      plexBox?.classList.toggle("hidden", provider !== "plex");

      if (libsBox) libsBox.innerHTML = `<div class="text-slate-500">${escapeHtml(t("loadingLibraries", "Loading libraries"))}</div>`;
      try {
        const libs = await loadLibraries(serverId);
        if (!libs.length) {
          if (libsBox) libsBox.innerHTML = `<div class="text-slate-500">${escapeHtml(t("noLibrariesServer", "No libraries on this server"))}</div>`;
          return;
        }

        if (libsBox) {
          libsBox.innerHTML = libs.map((library) => `
            <label class="flex items-center justify-between gap-2 py-1">
              <span class="text-slate-200">${escapeHtml(library.server_name ? `${library.server_name} - ` : "")}${escapeHtml(library.name)}</span>
              <input type="checkbox" data-lib-id="${library.id}">
            </label>`).join("");

          libsBox.querySelectorAll("input[data-lib-id]").forEach((checkbox) => {
            checkbox.addEventListener("change", () => {
              const id = parseInt(checkbox.getAttribute("data-lib-id"), 10);
              if (checkbox.checked) {
                if (!block.library_ids.includes(id)) block.library_ids.push(id);
              } else {
                block.library_ids = block.library_ids.filter((value) => value !== id);
              }
            });
          });
        }
      } catch (_) {
        if (libsBox) libsBox.innerHTML = `<div class="text-red-400">${escapeHtml(t("failedLibraries", "Unable to load libraries"))}</div>`;
      }
    });

    node.querySelectorAll('[data-field="jellyfin_password"]').forEach((input) => {
      input.addEventListener("input", () => { block.jellyfin_password = input.value; });
    });
    node.querySelectorAll('[data-field="jellyfin_force_password_change"]').forEach((input) => {
      input.addEventListener("change", () => { block.jellyfin_force_password_change = input.checked; });
    });
    node.querySelectorAll('[data-field="enqueue_plex_jobs"]').forEach((input) => {
      input.addEventListener("change", () => { block.enqueue_plex_jobs = input.checked; });
    });
    node.querySelectorAll("[data-plex-flag]").forEach((input) => {
      const key = input.getAttribute("data-plex-flag");
      const update = () => {
        if (!block.plex_share) block.plex_share = {};
        block.plex_share[key] = input.type === "checkbox" ? input.checked : input.value;
      };
      input.addEventListener("input", update);
      input.addEventListener("change", update);
    });

    return node;
  }

  function addServerBlock() {
    const id = Math.random().toString(16).slice(2);
    const block = { id, server_id: null, library_ids: [], provider: null };
    state.blocks.push(block);
    renderBlock(id);
  }

  function removeServerBlock(blockId) {
    state.blocks = state.blocks.filter((block) => block.id !== blockId);
    const container = document.getElementById("cu_servers_container");
    if (container) container.innerHTML = "";
    state.blocks.forEach((block) => renderBlock(block.id));
  }

  async function submit() {
    const button = document.getElementById("cu_submit");
    if (button) button.disabled = true;
    feedback(t("creating", "Creating..."));

    try {
      const payload = {
        email: document.getElementById("cu_email")?.value.trim() || "",
        second_email: document.getElementById("cu_second_email")?.value.trim() || "",
        username: document.getElementById("cu_username")?.value.trim() || "",
        firstname: document.getElementById("cu_firstname")?.value.trim() || "",
        lastname: document.getElementById("cu_lastname")?.value.trim() || "",
        expiration_date: document.getElementById("cu_expiration")?.value || "",
        subscription_template_id: document.getElementById("cu_subscription_template_id")?.value || "",
        referrer_user_id: document.getElementById("cu_referrer_user_id")?.value || "",
        notes: document.getElementById("cu_notes")?.value.trim() || "",
        servers: state.blocks.filter((block) => block.server_id).map((block) => ({
          server_id: block.server_id,
          library_ids: block.library_ids || [],
          jellyfin_password: block.jellyfin_password || "",
          jellyfin_force_password_change: !!block.jellyfin_force_password_change,
          plex_share: block.plex_share || {},
          enqueue_plex_jobs: !!block.enqueue_plex_jobs,
        })),
      };

      if (!payload.servers.length) {
        feedback(t("selectOneServer", "Select at least one server."), "error");
        return;
      }

      const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute("content") || document.querySelector('input[name="_csrf_token"]')?.value || window.csrfToken || "";
      const response = await fetch(api.create || "/api/users/create", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(payload),
      });

      const raw = await response.text();
      let data;
      try { data = JSON.parse(raw); }
      catch (_) {
        data = {
          ok: false,
          error: raw && !raw.toLowerCase().includes("<!doctype html") ? raw : t("serverCreateError", "Server error during user creation. Check backend logs."),
        };
      }

      if (!response.ok || !data.ok) {
        feedback(data.error || t("createFailed", "Create failed"), "error");
        return;
      }

      let message = `${t("userCreated", "User created")} (vodum_user_id=${data.vodum_user_id}).`;
      if (data.provider_errors?.length) message += ` Provider errors: ${data.provider_errors.join(" | ")}`;
      if (data.mailing_errors?.length) message += ` Mailing errors: ${data.mailing_errors.join(" | ")}`;
      feedback(message, "success");
      setTimeout(() => window.location.reload(), 800);
    } catch (error) {
      feedback(error.message || String(error), "error");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function bindCreateUser() {
    if (window.VodumCreateUser) return;

    window.VodumCreateUser = { open, close, addServerBlock, removeServerBlock, submit, openReferrerModal, closeReferrerModal, clearReferrer };

    document.getElementById("cu_referrer_search")?.addEventListener("input", (event) => {
      loadReferrerCandidates((event.target.value || "").trim());
    });

    document.getElementById("cu_referrer_results")?.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-id]");
      if (!button) return;
      if (!button.dataset.id) {
        clearReferrer();
        closeReferrerModal();
        return;
      }
      setReferrer({ id: button.dataset.id, username: button.dataset.username || "", email: button.dataset.email || "" });
    });

    document.getElementById("btn_create_user")?.addEventListener("click", async () => {
      try {
        if (!state.servers.length) await initServers();
        window.VodumCreateUser.open();
      } catch (error) {
        const message = t("failedServers", "Unable to load servers: {error}").replace("{error}", error.message || error);
        if (window.vodumFlash) window.vodumFlash("error", message);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", bindCreateUser);
})();

