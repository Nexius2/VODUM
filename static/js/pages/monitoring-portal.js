(function () {
  const source = document.getElementById("portal-usage-data");
  if (!source || typeof Chart === "undefined") return;
  const data = JSON.parse(source.textContent);
  const labels = data.timeline.map(row => row.day);
  const options = {responsive: true, maintainAspectRatio: false,
    scales: {y: {beginAtZero: true, ticks: {precision: 0, color: "#94a3b8"}}, x: {ticks: {color: "#94a3b8", maxTicksLimit: 10}}},
    plugins: {legend: {labels: {color: "#cbd5e1"}}}};
  new Chart(document.getElementById("portal-login-chart"), {type: "line", data: {labels,
    datasets: [{label: data.logins, data: data.timeline.map(row => row.logins), borderColor: "#818cf8", tension: 0.2}]}, options});
  new Chart(document.getElementById("portal-action-chart"), {type: "bar", data: {labels,
    datasets: [{label: data.invitations, data: data.timeline.map(row => row.invitations), backgroundColor: "#34d399"},
      {label: data.changes, data: data.timeline.map(row => row.changes), backgroundColor: "#38bdf8"}]}, options});
})();
