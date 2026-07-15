// ===========================================================
// VODUM Front-End JS
// Gestion onglets, auto-refresh intelligent, actions AJAX
// + compat HTMX (Monitoring tabs)
// ===========================================================

// Artwork is also injected by HTMX, so handle failures at document level.
// This prevents broken-image icons or alt text from shifting a media card.

// ------------ MOBILE MENU ---------------------------------

function initMobileMenu() {
  const menu = document.getElementById("mobileMenu");
  const openBtn = document.getElementById("mobileMenuOpen");
  const closeBtn = document.getElementById("mobileMenuClose");
  const backdrop = document.getElementById("mobileMenuBackdrop");
  const mobileNav = document.getElementById("mobileMenuNav");
  const desktopNav = document.querySelector("#desktopSidebar nav");

  if (!menu || !openBtn || !closeBtn || !backdrop || !mobileNav || !desktopNav) return;

  if (!mobileNav.dataset.ready) {
    mobileNav.innerHTML = desktopNav.innerHTML;
    mobileNav.dataset.ready = "1";

    mobileNav.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        menu.classList.add("hidden");
        document.body.classList.remove("overflow-hidden");
      });
    });
  }

  function openMenu() {
    menu.classList.remove("hidden");
    document.body.classList.add("overflow-hidden");
  }

  function closeMenu() {
    menu.classList.add("hidden");
    document.body.classList.remove("overflow-hidden");
  }

  openBtn.addEventListener("click", openMenu);
  closeBtn.addEventListener("click", closeMenu);
  backdrop.addEventListener("click", closeMenu);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMenu();
  });
}

document.addEventListener("DOMContentLoaded", initMobileMenu);



document.addEventListener("error", (event) => {
  const image = event.target;
  if (image instanceof HTMLImageElement && image.classList.contains("js-artwork-image")) {
    image.remove();
  }
}, true);


window.__vodumDebounceSubmit = window.__vodumDebounceSubmit || (() => {
  let timer = null;
  return (form) => {
    if (!form) return;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => form.submit(), 500);
  };
})();

function initUserNotificationOrder() {
  const checkbox = document.getElementById("use_global_notifications_order_cb");
  const layer = document.getElementById("user_notif_order_layer");
  const list = document.getElementById("user-notif-order-list");
  const hidden = document.getElementById("user_notifications_order_hidden");
  if (!checkbox || !layer || !list || !hidden || list.dataset.vodumBound === "1") return;
  list.dataset.vodumBound = "1";

  function updateHidden() {
    const items = Array.from(list.querySelectorAll("li[data-channel]"));
    hidden.value = items.map((item) => item.dataset.channel).filter(Boolean).join(",");
  }

  function moveItem(item, direction) {
    if (!item) return;
    if (direction === "up" && item.previousElementSibling) {
      list.insertBefore(item, item.previousElementSibling);
    }
    if (direction === "down" && item.nextElementSibling) {
      list.insertBefore(item.nextElementSibling, item);
    }
    updateHidden();
  }

  function syncLayerState() {
    layer.classList.toggle("opacity-50", checkbox.checked);
    layer.classList.toggle("pointer-events-none", checkbox.checked);
  }

  list.addEventListener("click", (event) => {
    const item = event.target.closest("li[data-channel]");
    if (!item) return;
    if (event.target.closest(".order-up")) moveItem(item, "up");
    if (event.target.closest(".order-down")) moveItem(item, "down");
  });

  checkbox.addEventListener("change", syncLayerState);
  updateHidden();
  syncLayerState();
}

document.addEventListener("DOMContentLoaded", initUserNotificationOrder);
document.addEventListener("htmx:load", initUserNotificationOrder);
// ------------ UTILITAIRES ---------------------------------

async function apiGet(url) {
  const response = await fetch(url, { cache: "no-cache" });

  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`GET ${url} -> HTTP ${response.status}\n${text}`);
  }
  if (!contentType.includes("application/json")) {
    const text = await response.text().catch(() => "");
    throw new Error(`GET ${url} -> Expected JSON, got ${contentType}\n${text}`);
  }
  return response.json();
}

async function apiPost(url, body = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });

  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`POST ${url} -> HTTP ${response.status}\n${text}`);
  }
  if (!contentType.includes("application/json")) {
    const text = await response.text().catch(() => "");
    return { ok: true, raw: text };
  }
  return response.json();
}

function qs(sel) { return document.querySelector(sel); }
function qsa(sel) { return document.querySelectorAll(sel); }

function htmlEscape(str) {
  return String(str ?? "").replace(/[&<>"']/g, (m) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[m]));
}

function vodumParseDate(value) {
  if (!value) return null;

  const raw = String(value).trim();
  if (!raw || raw === "-" || raw === "—") return null;

  if (/^\d+$/.test(raw)) {
    let ts = Number(raw);
    if (ts > 1000000000000) {
      ts = Math.floor(ts / 1000);
    }
    return new Date(ts * 1000);
  }

  if (raw.endsWith("Z") || /[+-]\d{2}:\d{2}$/.test(raw)) {
    return new Date(raw);
  }

  return new Date(raw.replace(" ", "T") + "Z");
}

function vodumFormatDateTime(value, mode = "datetime") {
  const date = vodumParseDate(value);
  if (!date || Number.isNaN(date.getTime())) {
    return value || "-";
  }

  if (mode === "short") {
    return date.toLocaleString(undefined, {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

function vodumRefreshBrowserDateTimes(root = document) {
  root.querySelectorAll("[data-vodum-datetime]").forEach((el) => {
    const value = el.dataset.vodumDatetime;
    const mode = el.dataset.vodumDatetimeMode || "datetime";
    el.textContent = vodumFormatDateTime(value, mode);
  });
}

window.vodumParseDate = vodumParseDate;
window.vodumFormatDateTime = vodumFormatDateTime;
window.vodumRefreshBrowserDateTimes = vodumRefreshBrowserDateTimes;

// ------------ ONGLET ACTIF (pages legacy avec .tab/.tab-content) --------

function activateTab(tabName) {
  if (!tabName) return;

  const tabEl = document.getElementById(`tab-${tabName}`);
  const viewEl = document.getElementById(`view-${tabName}`);

  // Si pas d’onglets sur cette page, on sort (évite crash)
  if (!tabEl || !viewEl) return;

  document.querySelectorAll(".tab").forEach(t => t?.classList?.remove("active"));
  document.querySelectorAll(".tab-content").forEach(v => v?.classList?.add("hidden"));

  tabEl.classList.add("active");
  viewEl.classList.remove("hidden");

  localStorage.setItem("vodum_active_tab", tabName);
}

function initTabs() {
  const tabs = qsa(".tab");
  const views = qsa(".tab-content");

  // Si la page n'a pas le système d'onglets, ne rien faire.
  if (!tabs.length || !views.length) return;

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      if (!name) return;
      activateTab(name);
    });
  });

  const saved = localStorage.getItem("vodum_active_tab");
  if (saved && qs(`#tab-${saved}`) && qs(`#view-${saved}`)) {
    activateTab(saved);
    return;
  }

  if (qs("#tab-users") && qs("#view-users")) {
    activateTab("users");
    return;
  }

  const first = tabs[0]?.dataset?.tab;
  if (first && qs(`#tab-${first}`) && qs(`#view-${first}`)) {
    activateTab(first);
  }
}

// ------------ AUTO-REFRESH INTELLIGENT (pages legacy) -------------------

let refreshIntervals = {
  users: 15000,
  servers: 15000,
  libraries: 30000,
  tasks: 5000,
  logs: 8000
};

async function refreshActiveTab() {
  const active = localStorage.getItem("vodum_active_tab");
  if (!active) return;

  // Si la vue n’existe pas sur cette page → stop
  if (!document.getElementById(`view-${active}`)) return;

  try {
    switch (active) {
      case "users":      await refreshUsers(); break;
      case "servers":    await refreshServers(); break;
      case "libraries":  await refreshLibraries(); break;
      case "tasks":      await refreshTasks(); break;
      case "logs":       await refreshLogs(); break;
    }
  } catch (e) {
    console.error("[vodum] refresh failed:", e);
  }

  const delay = refreshIntervals[active] ?? 15000;
  setTimeout(refreshActiveTab, delay);
}

// ------------ RENDUS (legacy tables) ------------------------------------

async function refreshUsers() {
  const tbody = qs("#users-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/users");
  tbody.innerHTML = data.map(u => `
    <tr>
      <td>${htmlEscape(u.title || u.username)}</td>
      <td>${htmlEscape(u.email || "")}</td>
      <td>${Number(u.libraries_count ?? 0)}</td>
      <td>${Number(u.servers_count ?? 0)}</td>
      <td>${htmlEscape(u.status ?? "")}</td>
    </tr>
  `).join("");
}

async function refreshServers() {
  const tbody = qs("#servers-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/servers");
  tbody.innerHTML = data.map(s => `
    <tr>
      <td>${htmlEscape(s.name ?? "")}</td>
      <td>${htmlEscape(s.type ?? "")}</td>
      <td>${htmlEscape(s.status ?? "")}</td>
      <td>${htmlEscape(s.libraries ?? "")}</td>
    </tr>
  `).join("");
}

async function refreshLibraries() {
  const tbody = qs("#libraries-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/libraries");
  tbody.innerHTML = data.map(lib => `
    <tr>
      <td>${htmlEscape(lib.title ?? "")}</td>
      <td>${htmlEscape(lib.type ?? "")}</td>
      <td>${htmlEscape(lib.server_name ?? "")}</td>
      <td>${Number(lib.user_count ?? 0)}</td>
    </tr>
  `).join("");
}

async function refreshTasks() {
  const tbody = qs("#tasks-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/tasks");
  tbody.innerHTML = data.map(t => `
    <tr>
      <td>${htmlEscape(t.name ?? "")}</td>
      <td>${htmlEscape(t.status ?? "")}</td>
      <td>${htmlEscape(vodumFormatDateTime(t.last_run || "-"))}</td>
      <td>${htmlEscape(vodumFormatDateTime(t.next_run || "-"))}</td>
      <td>
        <button onclick="runTask(${Number(t.id)})">Run</button>
      </td>
    </tr>
  `).join("");
}

async function refreshLogs() {
  const tbody = qs("#logs-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/logs?limit=200");
  tbody.innerHTML = data.map(log => `
    <tr>
      <td>${htmlEscape(vodumFormatDateTime(log.date ?? log.created_at ?? ""))}</td>
      <td>${htmlEscape(log.level ?? "")}</td>
      <td>${htmlEscape(log.message ?? "")}</td>
    </tr>
  `).join("");
}

// ------------ ACTIONS ---------------------------------------

async function runTask(id) {
  try {
    await apiPost(`/tasks/run/${id}`);
    await refreshTasks();
  } catch (e) {
    console.error("[vodum] runTask failed:", e);
  }
}


function initUserMediaInfoToggles() {
  function wire(boxId, fadeId, btnId) {
    const box = document.getElementById(boxId);
    const fade = document.getElementById(fadeId);
    const btn = document.getElementById(btnId);
    if (!box || !btn) return;

    const labelMore = btn.dataset.more || btn.textContent || "Show more";
    const labelLess = btn.dataset.less || "Show less";

    // état initial = replié
    let expanded = false;
    btn.textContent = labelMore;

    btn.addEventListener("click", () => {
      expanded = !expanded;

      if (expanded) {
        box.classList.remove("max-h-48");
        box.classList.add("max-h-none");
        if (fade) fade.classList.add("hidden");
        btn.textContent = labelLess;
      } else {
        box.classList.remove("max-h-none");
        box.classList.add("max-h-48");
        if (fade) fade.classList.remove("hidden");
        btn.textContent = labelMore;
      }
    });
  }

  wire("plexBox", "plexFade", "plexToggle");
  wire("jellyfinBox", "jellyfinFade", "jellyfinToggle");
}

// ------------ INIT -------------------------------------------

window.addEventListener("DOMContentLoaded", () => {
  // Legacy tabs
  try { initTabs(); } catch (e) { console.error("[vodum] initTabs failed:", e); }
  try { refreshActiveTab(); } catch (e) { console.error("[vodum] refreshActiveTab failed:", e); }
  try { initUserMediaInfoToggles(); } catch (e) { console.error("[vodum] initUserMediaInfoToggles failed:", e); }
  try { vodumRefreshBrowserDateTimes(document); } catch (e) { console.error("[vodum] browser datetime failed:", e); }


  // Monitoring Activity charts (si la page est chargée directement sur Activity)
  try {
    if (typeof window.vodumInitMonitoringActivity === "function") {
      window.vodumInitMonitoringActivity(document);
    }
  } catch (e) {
    console.error("[vodum] init monitoring activity failed:", e);
  }
});

// ------------ HTMX HOOKS (Monitoring tabs) -------------------
// IMPORTANT: quand HTMX injecte un onglet, DOMContentLoaded ne se déclenche pas.
// Donc on relance les init JS ici.

document.body.addEventListener("htmx:afterSwap", function (event) {
  try { vodumRefreshBrowserDateTimes(event.target || document); } catch (e) { console.error("[vodum] htmx datetime failed:", e); }
});

// ------------ INDICATEUR ACTIVITÉ TASKS ----------------------

(function taskActivityIndicator() {
  const box = document.getElementById("taskActivity");
  const textEl = document.getElementById("taskActivityText");
  if (!box || !textEl) return;

  const idleDelayMs = 15000;
  const activeDelayMs = 2500;
  let timer = null;
  let lastHadActivity = false;

  function schedule(delayMs) {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(refresh, delayMs);
  }

  async function refresh() {
    if (document.hidden) {
      schedule(idleDelayMs);
      return;
    }

    try {
      const r = await fetch("/api/tasks/activity", { cache: "no-store" });
      if (!r.ok) throw new Error("bad status");
      const data = await r.json();
      const running = Number(data.running || 0);
      const queued = Number(data.queued || 0);
      const n = running + queued;
      lastHadActivity = n > 0;

      if (lastHadActivity) {
        const parts = [];
        if (running > 0) parts.push(`${running} running`);
        if (queued > 0) parts.push(`${queued} queued`);
        const label = textEl.dataset.label || "Tasks";
        textEl.textContent = `${label}: ${parts.join(" - ")}`;
        box.classList.remove("hidden");
      } else {
        box.classList.add("hidden");
      }
    } catch {
      lastHadActivity = false;
      box.classList.add("hidden");
    }

    schedule(lastHadActivity ? activeDelayMs : idleDelayMs);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh();
  });

  refresh();
})();




// -----------------------------------------------------------
// Flash banners (client-side) - same style as server flash()
// -----------------------------------------------------------
const vodumStaticBaseUrl = (() => {
  const script = document.currentScript;
  if (!script || !script.src) return "/static/";
  return new URL("../", script.src).href;
})();

function vodumStaticUrl(path) {
  return new URL(path.replace(/^\/+/, ""), vodumStaticBaseUrl).href;
}

window.vodumFlash = function(category, message, autoHideMs = 4000) {
  const box = document.getElementById("clientFlash");
  if (!box) return;

  const div = document.createElement("div");
  div.className = "text-xs px-3 py-2 rounded-lg";

  if (category === "success") {
    div.classList.add("bg-emerald-900/40", "text-emerald-100");
  } else if (category === "error") {
    div.classList.add("bg-rose-900/40", "text-rose-100");
  } else {
    div.classList.add("bg-slate-800", "text-slate-100");
  }

  div.textContent = message;

  box.classList.remove("hidden");
  box.appendChild(div);

  if (autoHideMs && autoHideMs > 0) {
    setTimeout(() => {
      div.remove();
      if (!box.children.length) box.classList.add("hidden");
    }, autoHideMs);
  }
};

// ------------ DATE PICKERS (Flatpickr lazy loader) -----------------------
// Loads Flatpickr only on pages/fragments that expose input.vodum-date.
(function vodumDatePickers() {
  const flatpickrCssUrl = vodumStaticUrl("vendor/flatpickr/flatpickr.min.css");
  const flatpickrJsUrl = vodumStaticUrl("vendor/flatpickr/flatpickr.min.js");
  let flatpickrPromise = null;
  let localePromise = null;

  function loadStyleOnce(id, href) {
    if (document.getElementById(id)) return;
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }

  function loadScriptOnce(id, src) {
    const existing = document.getElementById(id);
    if (existing) {
      return existing.dataset.loaded === "1"
        ? Promise.resolve()
        : new Promise((resolve, reject) => {
            existing.addEventListener("load", resolve, { once: true });
            existing.addEventListener("error", reject, { once: true });
          });
    }

    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.id = id;
      script.src = src;
      script.async = true;
      script.onload = () => {
        script.dataset.loaded = "1";
        resolve();
      };
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  function getBaseLang() {
    const raw = (document.documentElement.getAttribute("lang") || "en").toLowerCase();
    return raw.split("-", 1)[0] || "en";
  }

  function ensureFlatpickr() {
    if (window.flatpickr) return Promise.resolve();
    if (!flatpickrPromise) {
      loadStyleOnce("vodum-flatpickr-css", flatpickrCssUrl);
      flatpickrPromise = loadScriptOnce("vodum-flatpickr-js", flatpickrJsUrl);
    }
    return flatpickrPromise;
  }

  function ensureLocale(base) {
    if (base === "en") return Promise.resolve();
    if (window.flatpickr && window.flatpickr.l10ns && window.flatpickr.l10ns[base]) {
      return Promise.resolve();
    }
    if (!localePromise) {
      localePromise = loadScriptOnce("vodum-flatpickr-locale-" + base, vodumStaticUrl(`vendor/flatpickr/l10n/${base}.js`))
        .catch(() => undefined);
    }
    return localePromise;
  }

  async function initVodumDatePickers(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const inputs = Array.from(scope.querySelectorAll("input.vodum-date"));
    if (!inputs.length) return;

    await ensureFlatpickr();
    if (!window.flatpickr) return;

    const base = getBaseLang();
    await ensureLocale(base);

    const locale =
      (window.flatpickr.l10ns && window.flatpickr.l10ns[base])
        ? window.flatpickr.l10ns[base]
        : window.flatpickr.l10ns.default;

    inputs.forEach((el) => {
      if (el._vodumFlatpickr) return;
      el._vodumFlatpickr = flatpickr(el, {
        allowInput: true,
        dateFormat: "Y-m-d",
        locale: locale,
        disableMobile: true
      });
    });
  }

  window.vodumInitDatePickers = initVodumDatePickers;

  document.addEventListener("DOMContentLoaded", () => initVodumDatePickers(document));
  document.addEventListener("htmx:load", (event) => initVodumDatePickers(event.target));
})();

// ------------ CSRF FOR DYNAMIC POST FORMS / HTMX -------------------------
(function vodumCsrf() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  const csrfToken = meta ? meta.getAttribute("content") : "";
  if (!csrfToken) return;

  function ensureCsrfField(form) {
    if (!form || form.querySelector('input[name="_csrf_token"]')) return;

    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "_csrf_token";
    input.value = csrfToken;
    form.appendChild(input);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(ensureCsrfField);
  });

  document.addEventListener("submit", function (event) {
    const form = event.target;
    if (form && form.tagName === "FORM") {
      const method = (form.getAttribute("method") || "get").toLowerCase();
      if (method === "post") {
        ensureCsrfField(form);
      }
    }
  });

  document.body.addEventListener("htmx:configRequest", function (event) {
    event.detail.headers["X-CSRF-Token"] = csrfToken;
  });
})();

// ------------ MOBILE TABLES ---------------------------------------------
(function vodumMobileTables() {
  function shouldSkip(table) {
    return table.closest(".vodum-mobile-table-scroll, .overflow-x-auto, .table-responsive");
  }

  function enhanceMobileTables(root = document) {
    const scope = root && root.querySelectorAll ? root : document;
    const selector = scope === document ? "main table" : "table";
    const tables = Array.from(scope.querySelectorAll(selector));
    if (scope.matches && scope.matches("table")) {
      tables.unshift(scope);
    }

    tables.forEach((table) => {
      if (!table.closest("main") || shouldSkip(table) || !table.parentNode) return;

      const wrapper = document.createElement("div");
      wrapper.className = "vodum-mobile-table-scroll";
      wrapper.dataset.vodumMobileTable = "1";
      table.parentNode.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }

  window.vodumEnhanceMobileTables = enhanceMobileTables;
  document.addEventListener("DOMContentLoaded", () => enhanceMobileTables(document));
  document.addEventListener("htmx:load", (event) => enhanceMobileTables(event.target));
})();
