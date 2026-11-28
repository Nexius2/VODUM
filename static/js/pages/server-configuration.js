(() => {
  // Compliance pages: overview list, Settings view and its side panel, deployments.
  const token = () => document.querySelector('meta[name="csrf-token"]')?.content || "";
  const pressed = (button) => button?.getAttribute("aria-pressed") === "true";

  function parseList(text) {
    try {
      const value = JSON.parse(text || "[]");
      return Array.isArray(value) ? value : [];
    } catch (error) {
      return [];
    }
  }

  // Reads or checks servers one at a time (a few in parallel), so a page never waits
  // on every server at once, whatever their number. Reloads when it is done.
  async function runProgressive(ids, url, text, label, options = {}) {
    const queue = ids.slice();
    const total = queue.length;
    let done = 0, failed = 0;
    const show = () => { if (text) text.textContent = `${label || ""} ${done}/${total}`.trim(); };
    show();
    async function worker() {
      while (queue.length) {
        const id = queue.shift();
        try {
          const response = await fetch(url.replace(/\/0(\/|$)/, `/${id}$1`), {
            method: "POST", credentials: "same-origin",
            headers: { "X-CSRF-Token": token(), "Accept": "application/json" },
          });
          const answer = response.ok ? await response.json() : { ok: false };
          if (!answer.ok) failed += 1;
        } catch (error) {
          failed += 1;
        }
        done += 1;
        show();
      }
    }
    const workers = [];
    for (let i = 0; i < Math.min(options.concurrency || 3, total); i += 1) workers.push(worker());
    await Promise.all(workers);
    if (options.reload !== false) window.location.reload();
    return { done, failed };
  }

  function bindProgressive(button, ids, url, text, label) {
    if (!button || !ids.length || button.dataset.running === "1") return null;
    button.dataset.running = "1";
    button.disabled = true;
    return runProgressive(ids, url, text, label);
  }

  // ------------------------------------------------------------------ overview
  function bindOverview(root) {
    if (root.dataset.overviewReady === "1") return;
    root.dataset.overviewReady = "1";
    const body = root.querySelector("[data-overview-body]");
    const rows = Array.from(root.querySelectorAll("[data-overview-row]"));
    const pager = root.querySelector("[data-overview-pager]");
    const size = Number(pager?.dataset.pageSize || 50);
    let page = 0;

    function bucket() {
      return root.querySelector("[data-overview-bucket][aria-pressed=true]")?.dataset.overviewBucket || "";
    }
    function sorter(kind) {
      const text = (row, name) => row.dataset[name] || "";
      if (kind === "name") return (a, b) => text(a, "name").localeCompare(text(b, "name"));
      if (kind === "drifts") return (a, b) => Number(b.dataset.drifts) - Number(a.dataset.drifts) || text(a, "name").localeCompare(text(b, "name"));
      if (kind === "checked") return (a, b) => text(b, "checked").localeCompare(text(a, "checked")) || text(a, "name").localeCompare(text(b, "name"));
      return (a, b) => Number(a.dataset.statusOrder) - Number(b.dataset.statusOrder)
        || Number(b.dataset.drifts) - Number(a.dataset.drifts) || text(a, "name").localeCompare(text(b, "name"));
    }
    function apply(resetPage) {
      if (resetPage) page = 0;
      const query = (root.querySelector("[data-overview-search]")?.value || "").trim().toLowerCase();
      const provider = root.querySelector("[data-overview-provider]")?.value || "";
      const group = root.querySelector("[data-overview-group]")?.value || "";
      const wanted = bucket();
      const sorted = rows.slice().sort(sorter(root.querySelector("[data-overview-sort]")?.value || "status"));
      if (body) sorted.forEach((row) => body.appendChild(row));
      const matching = sorted.filter((row) => (!query || row.dataset.search.includes(query))
        && (!provider || row.dataset.provider === provider)
        && (!group || row.dataset.groups.includes(`,${group},`))
        && (!wanted || row.dataset.bucket === wanted));
      const pages = Math.max(1, Math.ceil(matching.length / size));
      page = Math.min(page, pages - 1);
      const shown = new Set(matching.slice(page * size, (page + 1) * size));
      rows.forEach((row) => row.classList.toggle("hidden", !shown.has(row)));
      root.querySelector("[data-overview-no-match]")?.classList.toggle("hidden", !!matching.length || !rows.length);
      if (pager) {
        pager.classList.toggle("hidden", matching.length <= size);
        const info = pager.querySelector("[data-pager-info]");
        if (info) info.textContent = (pager.dataset.template || "{page}/{pages}")
          .replace("{page}", String(page + 1)).replace("{pages}", String(pages)).replace("{count}", String(matching.length));
        const prev = pager.querySelector("[data-pager-prev]");
        const next = pager.querySelector("[data-pager-next]");
        if (prev) prev.disabled = page === 0;
        if (next) next.disabled = page >= pages - 1;
      }
    }
    root.addEventListener("input", (event) => { if (event.target.closest("[data-overview-list]")) apply(true); });
    root.addEventListener("change", (event) => { if (event.target.closest("[data-overview-list]")) apply(true); });
    root.addEventListener("click", (event) => {
      const kpi = event.target.closest("[data-overview-bucket]");
      if (kpi) {
        const on = !pressed(kpi);
        root.querySelectorAll("[data-overview-bucket]").forEach((item) => item.setAttribute("aria-pressed", "false"));
        kpi.setAttribute("aria-pressed", on ? "true" : "false");
        apply(true);
      }
      // The whole line opens the server, except its own links, buttons and forms.
      const line = event.target.closest("[data-overview-row][data-href]");
      if (line && !event.target.closest("a, button, input, select, label, form")) {
        if (event.ctrlKey || event.metaKey) window.open(line.dataset.href, "_blank");
        else window.location.href = line.dataset.href;
      }
      if (event.target.closest("[data-pager-prev]")) { page = Math.max(0, page - 1); apply(false); }
      if (event.target.closest("[data-pager-next]")) { page += 1; apply(false); }
    });
    apply(true);
  }

  // ------------------------------------------------------------- settings view
  // "Show" keeps the settings of one kind only; the two "Include" boxes add settings
  // to every kind. With one server there is no "Show" choice: everything is listed.
  const SHOW = {
    everything: () => true,
    different: (data) => data.state === "different",
    off_profile: (data) => Number(data.offProfile) > 0,
    off_recommendation: (data) => Number(data.offRecommendation) > 0,
    recommended: (data) => data.recommended === "1",
  };

  function filterSettings(rows, options) {
    const counts = {};
    Object.keys(SHOW).forEach((name) => { counts[name] = 0; });
    const keep = SHOW[options.show] || SHOW.everything;
    const visible = rows.map((data) => {
      const base = (!options.category || data.category === options.category)
        && (!options.query || data.search.includes(options.query))
        // A search also finds advanced settings, as before.
        && (options.advanced || data.advanced !== "1" || options.query !== "")
        && (options.libraries || data.library !== "1");
      if (base) Object.keys(SHOW).forEach((name) => { if (SHOW[name](data)) counts[name] += 1; });
      return base && keep(data);
    });
    return { visible, counts };
  }

  function bindSettings(root) {
    if (root.dataset.settingsReady === "1") return;
    root.dataset.settingsReady = "1";
    const rows = Array.from(root.querySelectorAll("[data-settings-row]"));

    function apply() {
      const query = (root.querySelector("[data-settings-search]")?.value || "").trim().toLowerCase();
      const category = root.querySelector("[data-settings-category]")?.value || "";
      const current = root.querySelector("[data-settings-show][aria-checked=true]")?.dataset.settingsShow || "everything";
      const advanced = !!root.querySelector("[data-settings-advanced]")?.checked;
      const librariesBox = root.querySelector("[data-settings-libraries]");
      const libraries = !librariesBox || librariesBox.checked;
      const result = filterSettings(rows.map((row) => row.dataset), { query, category, show: current, advanced, libraries });
      rows.forEach((row, index) => row.classList.toggle("hidden", !result.visible[index]));
      const counts = result.counts;
      const visible = result.visible.filter(Boolean).length;
      root.querySelectorAll("[data-show-count]").forEach((badge) => {
        const count = counts[badge.dataset.showCount] || 0;
        badge.textContent = String(count);
        badge.closest("[data-settings-show]")?.classList.toggle("is-empty", count === 0);
      });
      root.querySelector("[data-settings-no-match]")?.classList.toggle("hidden", visible !== 0 || !rows.length);
    }

    root.addEventListener("input", (event) => {
      if (event.target.closest("[data-settings-list]")) apply();
      const search = event.target.closest("[data-picker-search]");
      if (search) {
        const query = search.value.trim().toLowerCase();
        root.querySelectorAll("[data-picker-item]").forEach((item) => {
          item.classList.toggle("hidden", !!query && !item.dataset.name.includes(query));
        });
      }
    });
    root.addEventListener("change", (event) => {
      if (event.target.closest("[data-settings-list]")) apply();
      const select = event.target.closest("[data-scope-select]");
      if (select) {
        const picker = root.querySelector("[data-server-picker]");
        if (select.value === "pick") {
          if (picker) { picker.open = true; picker.querySelector("[data-picker-search]")?.focus(); }
        } else {
          // A group or the whole platform: the ticked servers no longer apply.
          root.querySelectorAll("[data-server-picker] input[name=servers]").forEach((input) => { input.checked = false; });
          select.form?.submit();
        }
      }
    });
    root.addEventListener("submit", (event) => {
      const form = event.target.closest("[data-settings-scope]");
      if (!form) return;
      // Ticked servers win over a group; with none ticked the whole platform is shown.
      const select = form.querySelector("[data-scope-select]");
      const ticked = form.querySelectorAll("[data-server-picker] input[name=servers]:checked").length;
      if (select && (select.value === "pick" || ticked)) select.disabled = true;
    });
    root.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-settings-show]");
      if (toggle) {
        // One choice at a time: picking one always replaces the previous one.
        root.querySelectorAll("[data-settings-show]").forEach((item) => item.setAttribute("aria-checked", item === toggle ? "true" : "false"));
        apply();
      }
      const all = event.target.closest("[data-picker-all], [data-picker-none]");
      if (all) {
        const on = all.matches("[data-picker-all]");
        root.querySelectorAll("[data-picker-item]:not(.hidden) input[name=servers]").forEach((input) => { input.checked = on; });
      }
      const refresh = event.target.closest("[data-config-refresh]");
      if (refresh) {
        const text = refresh.parentElement?.querySelector("[data-progress-text]");
        bindProgressive(refresh, parseList(refresh.dataset.ids), refresh.dataset.url, text, refresh.dataset.progressLabel);
      }
      const open = event.target.closest("[data-settings-open]");
      if (open) openDrawer(root, open.closest("[data-settings-row]"), open);
    });
    apply();

    // Servers never read yet are read once, on their own, when the page opens.
    const refresh = root.querySelector("[data-config-refresh]");
    const missing = parseList(refresh?.dataset.missing);
    if (refresh && missing.length) {
      bindProgressive(refresh, missing, refresh.dataset.url, refresh.parentElement?.querySelector("[data-progress-text]"),
        refresh.dataset.progressLabel);
    }
  }

  // ------------------------------------------------------------------ drawer
  let lastOpener = null;

  function closeDrawer(root) {
    const drawer = root.querySelector("[data-settings-drawer]");
    if (!drawer || drawer.classList.contains("hidden")) return;
    drawer.classList.add("hidden");
    root.querySelector("[data-drawer-backdrop]")?.classList.add("hidden");
    drawer.replaceChildren();
    document.body.classList.remove("config-drawer-open");
    lastOpener?.focus?.();
  }

  function note(drawer, text) {
    const message = document.createElement("p");
    message.className = "px-5 py-6 text-sm text-slate-400";
    message.setAttribute("role", "status");
    message.textContent = text || "";
    drawer.replaceChildren(message);
  }

  async function openDrawer(root, row, opener) {
    const drawer = root.querySelector("[data-settings-drawer]");
    if (!drawer || !row) return;
    lastOpener = opener;
    drawer.classList.remove("hidden");
    root.querySelector("[data-drawer-backdrop]")?.classList.remove("hidden");
    document.body.classList.add("config-drawer-open");
    note(drawer, drawer.dataset.loading);
    const params = new URLSearchParams(root.dataset.scopeQuery || "");
    params.set("key", row.dataset.key);
    params.set("back", root.dataset.back || "");
    drawer.dataset.key = row.dataset.key;
    try {
      const response = await fetch(`${root.dataset.detailUrl}?${params}`, {
        credentials: "same-origin", headers: { "HX-Request": "true" },
      });
      if (!response.ok) throw new Error("detail_failed");
      const html = await response.text();
      if (drawer.dataset.key !== row.dataset.key || drawer.classList.contains("hidden")) return;
      drawer.innerHTML = html;
      window.htmx?.process?.(drawer);
      bindDetail(drawer.querySelector("[data-setting-detail]"));
      drawer.querySelector("[data-drawer-close]")?.focus();
    } catch (error) {
      if (drawer.dataset.key === row.dataset.key) note(drawer, drawer.dataset.failed);
    }
  }

  function bindDrawerClose(root) {
    if (root.dataset.drawerReady === "1") return;
    root.dataset.drawerReady = "1";
    root.addEventListener("click", (event) => {
      if (event.target.closest("[data-drawer-close], [data-drawer-backdrop]")) closeDrawer(root);
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDrawer(root);
    });
  }

  function choiceLabel(detail, choices, type, value) {
    const choice = choices.find((item) => String(item.value) === value);
    if (choice) return String(choice.label ?? value);
    if (type === "bool" || value === "true" || value === "false") {
      if (value === "true") return detail.dataset.labelYes || value;
      if (value === "false") return detail.dataset.labelNo || value;
    }
    return value === "" ? "∅" : value;
  }

  function buildControl(detail, form) {
    const type = form.dataset.type || "";
    const choices = parseList(form.dataset.choices);
    const recommended = form.dataset.recommended || "";
    let input;
    if (choices.length || type === "bool") {
      input = document.createElement("select");
      const options = choices.length ? choices.map((item) => String(item.value))
        : ["true", "false"];
      options.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = choiceLabel(detail, choices, type, value);
        input.appendChild(option);
      });
      if (recommended && options.includes(recommended)) input.value = recommended;
    } else {
      input = document.createElement("input");
      input.type = ["int", "integer", "double"].includes(type) ? "number" : "text";
      if (type === "double") input.step = "any";
      input.value = recommended;
    }
    input.id = "detail-value";
    input.className = "config-edit-control w-full";
    input.setAttribute("data-detail-value", "");
    form.querySelector("[data-detail-control]")?.replaceChildren(input);
    return input;
  }

  function bindDetail(detail) {
    if (!detail || detail.dataset.ready === "1") return;
    detail.dataset.ready = "1";
    const form = detail.querySelector("[data-detail-edit]");
    const targets = () => Array.from(detail.querySelectorAll("[data-edit-target]"));
    const input = form ? buildControl(detail, form) : null;

    function refresh() {
      if (!form) return;
      const chosen = targets().filter((box) => box.checked).length;
      // One preview reads each chosen server again, so it is limited (VODUM's deployment limit).
      const max = Number(form.dataset.max || 0);
      const tooMany = max > 0 && chosen > max;
      // Servers that already have the chosen value: nothing to preview for them.
      const value = String(input?.value ?? "").trim();
      const toChange = targets().filter((box) => box.checked && box.dataset.current !== value).length;
      const nothing = chosen > 0 && toChange === 0;
      const count = form.querySelector("[data-detail-count]");
      if (count) {
        const template = tooMany ? form.dataset.maxTemplate || "{max}"
          : nothing ? form.dataset.sameTemplate || "{count}" : form.dataset.countTemplate || "{count}";
        count.textContent = template.replace("{count}", String(chosen)).replace("{max}", String(max));
        count.classList.toggle("text-amber-300", tooMany || nothing);
      }
      const submit = form.querySelector("button[type=submit]");
      if (submit) submit.disabled = chosen === 0 || tooMany || nothing;
    }

    detail.addEventListener("change", refresh);
    detail.addEventListener("click", (event) => {
      const group = event.target.closest("[data-select-group]");
      if (group) {
        group.closest("[data-detail-group]").querySelectorAll("[data-edit-target]").forEach((box) => { box.checked = true; });
        refresh();
      }
      const expand = event.target.closest("[data-detail-expand]");
      if (expand) {
        expand.closest("[data-detail-group]")?.querySelector("[data-detail-servers]")?.classList.remove("is-collapsed");
        expand.remove();
      }
      const select = event.target.closest("[data-select]");
      if (select) {
        const kind = select.dataset.select;
        targets().forEach((box) => {
          const server = box.closest("[data-detail-server]");
          box.checked = kind === "all"
            || (kind === "off_profile" && server?.dataset.offProfile === "1")
            || (kind === "off_recommendation" && server?.dataset.offRecommendation === "1");
        });
        refresh();
      }
      if (event.target.closest("[data-use-recommended]") && input) {
        input.value = form.dataset.recommended || "";
        input.focus();
        refresh();
      }
    });
    input?.addEventListener("input", refresh);
    form?.addEventListener("submit", (event) => {
      const value = String(input?.value ?? "").trim();
      const edits = targets().filter((box) => box.checked && box.dataset.current !== value)
        .map((box) => ({ server_id: Number(box.value), key: box.dataset.key, value }));
      if (!edits.length) { event.preventDefault(); return; }
      form.querySelector("[data-detail-edits]").value = JSON.stringify(edits);
      const button = form.querySelector("button[type=submit]");
      if (button) { button.disabled = true; button.textContent = button.dataset.loadingLabel || button.textContent; }
    });
    refresh();
  }

  // Profile detail: search inside the saved settings.
  function applyProfile(root) {
    const query = (root.querySelector("[data-profile-search]")?.value || "").trim().toLowerCase();
    root.querySelectorAll("[data-profile-row]").forEach((row) => {
      row.classList.toggle("hidden", !!query && !row.dataset.search.includes(query));
    });
  }

  function bind(root, handler) {
    if (root.dataset.filtersReady === "1") return;
    root.dataset.filtersReady = "1";
    root.addEventListener("input", () => handler(root));
    root.addEventListener("change", () => handler(root));
    handler(root);
  }

  // Elements matching the selector inside the scope, and the scope itself (htmx
  // gives the swapped element itself as the loaded element).
  function within(base, selector) {
    const found = Array.from(base.querySelectorAll(selector));
    if (base !== document && base.matches?.(selector)) found.unshift(base);
    return found;
  }

  function init(scope) {
    const base = scope && scope.querySelectorAll ? scope : document;
    within(base, "[data-config-overview]").forEach(bindOverview);
    within(base, "[data-config-settings]").forEach((root) => { bindSettings(root); bindDrawerClose(root); });
    within(base, "[data-config-profile-form]").forEach((root) => bind(root, applyProfile));
    // Checks: one server at a time when the page knows them, otherwise the plain form.
    within(base, "form[data-config-check-form], form[data-config-plan-form]").forEach((form) => {
      if (form.dataset.checkReady === "1") return;
      form.dataset.checkReady = "1";
      form.addEventListener("submit", (event) => {
        const button = form.querySelector("button[type=submit]");
        const ids = parseList(form.dataset.configProgressive);
        if (ids.length && form.dataset.progressUrl && window.fetch) {
          event.preventDefault();
          bindProgressive(button, ids, form.dataset.progressUrl, form.querySelector("[data-progress-text]"),
            form.dataset.progressLabel);
          return;
        }
        if (!button) return;
        button.disabled = true;
        button.textContent = button.dataset.loadingLabel || button.textContent;
      });
    });
  }

  // Deployment: apply the confirmed changes one server at a time, each one verified
  // by the server before the next starts. A failure never stops the other servers.
  async function runDeployment(page) {
    if (page.dataset.running === "1" || page.dataset.status !== "running") return;
    page.dataset.running = "1";
    const progress = page.querySelector("[data-deploy-progress]");
    const queue = [...page.querySelectorAll('[data-deploy-server][data-state="pending"]')];
    let done = 0, changed = 0;
    for (const block of queue) {
      if (progress) progress.textContent = `${progress.dataset.runningLabel || ""} ${done + 1}/${queue.length}`;
      try {
        const response = await fetch(block.dataset.applyUrl, {
          method: "POST", credentials: "same-origin",
          headers: { "X-CSRF-Token": token(), "Accept": "text/html" },
        });
        if (response.ok) {
          const html = await response.text();
          if (!html.includes('data-state="pending"')) changed += 1;
          block.outerHTML = html;
        }
      } catch (error) {
        // Network error: the server keeps its pending changes and can be retried.
      }
      done += 1;
    }
    // Reload for the final summary; never loop on servers that stay pending.
    if (changed) window.location.reload();
    else if (progress) progress.textContent = "";
  }

  window.vodumServerConfiguration = { runProgressive, filterSettings, init };
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-config-deployment-page]").forEach(runDeployment);
  });
  document.addEventListener("DOMContentLoaded", () => init(document));
  document.addEventListener("htmx:load", (event) => init(event.target));
})();
