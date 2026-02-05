// ===========================================================
// VODUM Front-End JS
// Gestion onglets, auto-refresh intelligent, actions AJAX
// + compat HTMX (Monitoring tabs)
// ===========================================================

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
  tbody.innerHTML = "";

  data.forEach(u => {
    tbody.innerHTML += `
      <tr>
        <td>${htmlEscape(u.title || u.username)}</td>
        <td>${htmlEscape(u.email || "")}</td>
        <td>${Number(u.libraries_count ?? 0)}</td>
        <td>${Number(u.servers_count ?? 0)}</td>
        <td>${htmlEscape(u.status ?? "")}</td>
      </tr>
    `;
  });
}

async function refreshServers() {
  const tbody = qs("#servers-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/servers");
  tbody.innerHTML = "";

  data.forEach(s => {
    tbody.innerHTML += `
      <tr>
        <td>${htmlEscape(s.name ?? "")}</td>
        <td>${htmlEscape(s.type ?? "")}</td>
        <td>${htmlEscape(s.status ?? "")}</td>
        <td>${htmlEscape(s.libraries ?? "")}</td>
      </tr>
    `;
  });
}

async function refreshLibraries() {
  const tbody = qs("#libraries-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/libraries");
  tbody.innerHTML = "";

  data.forEach(lib => {
    tbody.innerHTML += `
      <tr>
        <td>${htmlEscape(lib.title ?? "")}</td>
        <td>${htmlEscape(lib.type ?? "")}</td>
        <td>${htmlEscape(lib.server_name ?? "")}</td>
        <td>${Number(lib.user_count ?? 0)}</td>
      </tr>
    `;
  });
}

async function refreshTasks() {
  const tbody = qs("#tasks-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/tasks");
  tbody.innerHTML = "";

  data.forEach(t => {
    tbody.innerHTML += `
      <tr>
        <td>${htmlEscape(t.name ?? "")}</td>
        <td>${htmlEscape(t.status ?? "")}</td>
        <td>${htmlEscape(t.last_run || "-")}</td>
        <td>${htmlEscape(t.next_run || "-")}</td>
        <td>
          <button onclick="runTask(${Number(t.id)})">Run</button>
        </td>
      </tr>
    `;
  });
}

async function refreshLogs() {
  const tbody = qs("#logs-table-body");
  if (!tbody) return;

  const data = await apiGet("/api/logs?limit=200");
  tbody.innerHTML = "";

  data.forEach(log => {
    tbody.innerHTML += `
      <tr>
        <td>${htmlEscape(log.date ?? "")}</td>
        <td>${htmlEscape(log.level ?? "")}</td>
        <td>${htmlEscape(log.message ?? "")}</td>
      </tr>
    `;
  });
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

// ------------ INIT -------------------------------------------

window.addEventListener("DOMContentLoaded", () => {
  // Legacy tabs
  try { initTabs(); } catch (e) { console.error("[vodum] initTabs failed:", e); }
  try { refreshActiveTab(); } catch (e) { console.error("[vodum] refreshActiveTab failed:", e); }

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



// ------------ INDICATEUR ACTIVITÉ TASKS ----------------------

(function taskActivityIndicator() {
  const box = document.getElementById("taskActivity");
  const countEl = document.getElementById("taskActivityCount");
  if (!box || !countEl) return;

  async function refresh() {
    try {
      const r = await fetch("/api/tasks/activity", { cache: "no-store" });
      if (!r.ok) throw new Error("bad status");
      const data = await r.json();
      const n = Number(data.active || 0);

      if (n > 0) {
        countEl.textContent = n;
        box.classList.remove("hidden");
      } else {
        box.classList.add("hidden");
      }
    } catch {
      box.classList.add("hidden");
    }
  }

  refresh();
  setInterval(refresh, 2500);
})();




// -----------------------------------------------------------
// Flash banners (client-side) - same style as server flash()
// -----------------------------------------------------------
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
