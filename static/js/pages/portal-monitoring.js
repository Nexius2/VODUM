(function () {
  "use strict";
  document.addEventListener("DOMContentLoaded", function () {
    const tabs = Array.from(document.querySelectorAll("[data-monitoring-tab]"));
    const panels = Array.from(document.querySelectorAll("[data-monitoring-panel]"));
    function select(name) {
      tabs.forEach(function (tab) {
        const active = tab.dataset.monitoringTab === name;
        tab.classList.toggle("bg-slate-900", active);
        tab.classList.toggle("text-cyan-300", active);
        tab.classList.toggle("font-semibold", active);
        tab.classList.toggle("bg-slate-950", !active);
        tab.classList.toggle("text-slate-400", !active);
        tab.setAttribute("aria-selected", active ? "true" : "false");
      });
      panels.forEach(function (panel) {
        panel.classList.toggle("hidden", panel.dataset.monitoringPanel !== name);
      });
      if (window.history && window.history.replaceState) window.history.replaceState(null, "", `#${name}`);
    }
    tabs.forEach(function (tab) { tab.addEventListener("click", function () { select(tab.dataset.monitoringTab); }); });
    const initial = window.location.hash.slice(1);
    if (tabs.some(function (tab) { return tab.dataset.monitoringTab === initial; })) select(initial);

    const dataNode = document.getElementById("portal-monitoring-chart-data");
    if (!dataNode || !window.Chart) return;
    let data = {};
    try { data = JSON.parse(dataNode.textContent || "{}"); } catch (_) { return; }
    const palette = ["#3b82f6", "#10b981", "#ef4444", "#a78bfa", "#f59e0b", "#06b6d4"];
    const doughnutOptions = {responsive: true, maintainAspectRatio: false, animation: false, cutout: "70%", plugins: {legend: {display: false}}};
    const lineOptions = {responsive: true, maintainAspectRatio: false, animation: false, normalized: true, plugins: {legend: {labels: {color: "#94a3b8"}}}, scales: {x: {ticks: {color: "#64748b"}, grid: {color: "rgba(148,163,184,.08)"}}, y: {beginAtZero: true, ticks: {color: "#64748b"}, grid: {color: "rgba(148,163,184,.08)"}}}};
    function legend(id, rows, colors) {
      const root = document.getElementById(id); if (!root) return;
      const total = rows.reduce(function (sum, row) { return sum + Number(row.plays || 0); }, 0);
      rows.forEach(function (row, index) {
        const item = document.createElement("div"); item.className = "portal-monitoring-legend-row min-w-0";
        const left = document.createElement("span"); left.className = "flex min-w-0 items-center gap-2";
        const dot = document.createElement("i"); dot.className = "h-2.5 w-2.5 shrink-0 rounded-full"; dot.style.backgroundColor = colors[index];
        const label = document.createElement("span"); label.className = "min-w-0 break-words"; label.textContent = row.label;
        const value = document.createElement("span"); value.className = "shrink-0 whitespace-nowrap text-slate-500"; value.textContent = `${total ? Math.round(Number(row.plays || 0) * 100 / total) : 0}%`;
        left.append(dot, label); item.append(left, value); root.append(item);
      });
    }
    function doughnut(canvasId, legendId, rows) {
      const canvas = document.getElementById(canvasId); if (!canvas || !rows.length) return;
      const colors = rows.map(function (_, index) { return palette[index % palette.length]; });
      new Chart(canvas, {type: "doughnut", data: {labels: rows.map(r => r.label), datasets: [{data: rows.map(r => Number(r.plays || 0)), backgroundColor: colors, borderWidth: 0}]}, options: doughnutOptions});
      legend(legendId, rows, colors);
    }
    function line(canvasId, label, values, color) {
      const canvas = document.getElementById(canvasId); if (!canvas) return;
      new Chart(canvas, {type: "line", data: {labels: (data.daily || []).map(r => r.day), datasets: [{label, data: values, tension: .4, fill: true, borderWidth: 2, pointRadius: 3, borderColor: color, backgroundColor: `${color}18`}]}, options: lineOptions});
    }
    doughnut("portalChartMediaTypes", "portalLegendMediaTypes", data.mediaTypes || []);
    doughnut("portalChartServers", "portalLegendServers", data.servers || []);
    line("portalChartPlays", data.playsLabel || "Plays", (data.daily || []).map(r => Number(r.plays || 0)), "#10b981");
    line("portalChartWatch", data.hoursLabel || "Hours", (data.daily || []).map(r => Number(r.watch_ms || 0) / 3600000), "#3b82f6");
  });
})();
