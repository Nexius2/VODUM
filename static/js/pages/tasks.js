(function vodumTasksPage() {
  const configEl = document.getElementById("vodum-tasks-config");
  const tbody = document.getElementById("tasks-tbody");
  if (!configEl || !tbody) return;

  let config = {};
  try {
    config = JSON.parse(configEl.textContent || "{}");
  } catch (error) {
    console.error("[vodum] invalid tasks config", error);
    return;
  }

  const debugMode = Number(config.debugMode || 0) === 1;
  const labels = config.i18n || {};
  const actionUrl = config.actionUrl || "/tasks/action";
  const pollInterval = Number(config.pollIntervalMs || 3000);
  const escapeHtml = window.htmlEscape || ((value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  }[char])));

  async function refreshTasksTable() {
    try {
      const response = await fetch("/api/tasks/list", { cache: "no-store" });
      if (!response.ok) return;

      const data = await response.json();
      const tasks = Array.isArray(data.tasks) ? data.tasks : [];

      tbody.innerHTML = tasks.map((task) => `
        <tr class="border-b border-slate-800">
          ${debugMode ? `<td class="p-2">${Number(task.id || 0)}</td>` : ""}
          <td class="p-2">${escapeHtml(task.name_label || "")}</td>
          <td class="p-2">${escapeHtml(task.description_label || "-")}</td>
          <td class="p-2">${escapeHtml(task.schedule_human || "-")}</td>
          <td class="p-2">${renderStatus(task)}</td>
          <td class="p-2">${escapeHtml(task.last_run_human || "-")}</td>
          <td class="p-2">${escapeHtml(task.next_run_human || "-")}</td>
          <td class="p-2 text-center">${renderAction(task)}</td>
        </tr>
      `).join("");
    } catch (error) {
      console.error("[vodum] refreshTasksTable failed", error);
    }
  }

  function renderStatus(task) {
    if (!task.enabled) {
      return `<span class="px-2 py-1 rounded bg-gray-700 text-gray-300 text-xs">${escapeHtml(labels.disabled || "disabled")}</span>`;
    }

    switch (task.status) {
      case "running":
        return `<span class="px-2 py-1 rounded bg-blue-700 text-blue-100 text-xs">${escapeHtml(labels.running || "running")}</span>`;
      case "done":
        return `<span class="px-2 py-1 rounded bg-green-700 text-green-100 text-xs">${escapeHtml(labels.done || "done")}</span>`;
      case "error":
        return `<span class="px-2 py-1 rounded bg-red-700 text-red-100 text-xs">${escapeHtml(labels.error || "error")}</span>`;
      default:
        return `<span class="px-2 py-1 rounded bg-gray-600 text-gray-200 text-xs">${escapeHtml(labels.idle || "idle")}</span>`;
    }
  }

  function renderAction(task) {
    if (!task.enabled) {
      return `
        <button disabled class="px-3 py-1 rounded bg-gray-700 text-gray-400 opacity-50 cursor-not-allowed">
          ${escapeHtml(labels.disabled || "disabled")}
        </button>
      `;
    }

    if (task.status === "running" || task.status === "queued") {
      return `
        <button disabled class="px-3 py-1 rounded bg-slate-600 text-slate-300 opacity-50 cursor-wait">
          ${escapeHtml(labels.running || "running")}
        </button>
      `;
    }

    return `
      <form action="${escapeHtml(actionUrl)}" method="post">
        <input type="hidden" name="task_id" value="${Number(task.id || 0)}">
        <input type="hidden" name="action" value="run_now">
        <button class="px-3 py-1 bg-blue-600 hover:bg-blue-700 rounded text-white">
          ${escapeHtml(labels.run_now || "Run now")}
        </button>
      </form>
    `;
  }

  window.setInterval(refreshTasksTable, pollInterval);
})();