// ===========================================================
// VODUM Front-End JS
// Gestion des onglets, auto-refresh intelligent et actions AJAX
// ===========================================================

// ------------ UTILITAIRES ---------------------------------

async function apiGet(url) {
    const response = await fetch(url, { cache: "no-cache" });
    return response.json();
}

async function apiPost(url, body = {}) {
    const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
    });
    return response.json();
}

function qs(sel) { return document.querySelector(sel); }
function qsa(sel) { return document.querySelectorAll(sel); }

function htmlEscape(str) {
    return str.replace(/[&<>"']/g, function(m) {
        return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[m];
    });
}

// ------------ ONGLET ACTIF --------------------------------

function activateTab(tabName) {
    qsa(".tab").forEach(t => t.classList.remove("active"));
    qsa(".tab-content").forEach(c => c.classList.add("hidden"));

    qs(`#tab-${tabName}`).classList.add("active");
    qs(`#view-${tabName}`).classList.remove("hidden");

    localStorage.setItem("vodum_active_tab", tabName);
}

function initTabs() {
    qsa(".tab").forEach(tab => {
        tab.addEventListener("click", () => {
            activateTab(tab.dataset.tab);
        });
    });

    const saved = localStorage.getItem("vodum_active_tab");
    if (saved && qs(`#tab-${saved}`)) activateTab(saved);
    else activateTab("users");
}

// ------------ AUTO-REFRESH INTELLIGENT ---------------------

let refreshIntervals = {
    users: 15000,       // mise à jour seulement après sync
    servers: 15000,     // mise à jour du statut seulement
    libraries: 30000,
    tasks: 5000,
    logs: 8000
};

async function refreshActiveTab() {
    const active = localStorage.getItem("vodum_active_tab");
    if (!active) return;

    switch (active) {
        case "users": refreshUsers(); break;
        case "servers": refreshServers(); break;
        case "libraries": refreshLibraries(); break;
        case "tasks": refreshTasks(); break;
        case "logs": refreshLogs(); break;
    }

    setTimeout(refreshActiveTab, refreshIntervals[active]);
}

// ------------ RENDUS ----------------------------------------

async function refreshUsers() {
    const data = await apiGet("/api/users");
    const tbody = qs("#users-table-body");
    tbody.innerHTML = "";

    data.forEach(u => {
        tbody.innerHTML += `
            <tr>
                <td>${htmlEscape(u.title || u.username)}</td>
                <td>${htmlEscape(u.email || "")}</td>
                <td>${u.libraries_count}</td>
                <td>${u.servers_count}</td>
                <td>${u.status}</td>
            </tr>
        `;
    });
}

async function refreshServers() {
    const data = await apiGet("/api/servers");
    const tbody = qs("#servers-table-body");
    tbody.innerHTML = "";

    data.forEach(s => {
        tbody.innerHTML += `
            <tr>
                <td>${s.name}</td>
                <td>${s.type}</td>
                <td>${s.status}</td>
                <td>${s.libraries}</td>
            </tr>
        `;
    });
}

async function refreshLibraries() {
    const data = await apiGet("/api/libraries");
    const tbody = qs("#libraries-table-body");
    tbody.innerHTML = "";

    data.forEach(lib => {
        tbody.innerHTML += `
            <tr>
                <td>${htmlEscape(lib.title)}</td>
                <td>${htmlEscape(lib.type)}</td>
                <td>${htmlEscape(lib.server_name)}</td>
                <td>${lib.user_count}</td>
            </tr>
        `;
    });
}

async function refreshTasks() {
    const data = await apiGet("/api/tasks");
    const tbody = qs("#tasks-table-body");
    tbody.innerHTML = "";

    data.forEach(t => {
        tbody.innerHTML += `
            <tr>
                <td>${t.name}</td>
                <td>${t.status}</td>
                <td>${t.last_run || "-"}</td>
                <td>${t.next_run || "-"}</td>
                <td>
                    <button onclick="runTask(${t.id})">Run</button>
                </td>
            </tr>
        `;
    });
}

async function refreshLogs() {
    const data = await apiGet("/api/logs?limit=200");
    const tbody = qs("#logs-table-body");
    tbody.innerHTML = "";

    data.forEach(log => {
        tbody.innerHTML += `
            <tr>
                <td>${log.date}</td>
                <td>${htmlEscape(log.level)}</td>
                <td>${htmlEscape(log.message)}</td>
            </tr>
        `;
    });
}

// ------------ ACTIONS ---------------------------------------

async function runTask(id) {
    await apiPost(`/tasks/run/${id}`);
    refreshTasks();
}

// ------------ INIT -------------------------------------------

window.addEventListener("DOMContentLoaded", () => {
    initTabs();
    refreshActiveTab();
});

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
