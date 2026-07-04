(function () {
  const configNode = document.getElementById("monitoring-user-chart-config");
  if (!configNode) return;

  let config = {};
  try {
    config = JSON.parse(configNode.textContent || "{}");
  } catch (error) {
    config = {};
  }

  function waitForChart(maxMs = 8000) {
    const start = Date.now();
    return new Promise((resolve, reject) => {
      const tick = () => {
        if (window.Chart) return resolve();
        if (Date.now() - start > maxMs) return reject(new Error("Chart.js not loaded"));
        setTimeout(tick, 50);
      };
      tick();
    });
  }

  async function fetchJSON(url) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status} on ${url}`);
    return res.json();
  }

  function hoursFromMs(ms) { return (Number(ms || 0) / 3600000); }

  function baseLineOpts() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      normalized: true,
      plugins: {
        legend: { labels: { color: "#94a3b8" } }
      },
      scales: {
        x: { ticks: { color: "#64748b" }, grid: { color: "rgba(148,163,184,0.08)" } },
        y: { ticks: { color: "#64748b" }, grid: { color: "rgba(148,163,184,0.08)" }, beginAtZero: true }
      }
    };
  }

  function doughnutOpts() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      cutout: "70%",
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true }
      }
    };
  }

  function makeLegend(container, labels, values, colors) {
    if (!container) return;
    const total = values.reduce((a, b) => a + (Number(b) || 0), 0) || 0;

    container.innerHTML = "";
    labels.forEach((label, i) => {
      const value = Number(values[i] || 0);
      if (!value) return;
      const pct = total ? Math.round((value / total) * 100) : 0;

      const row = document.createElement("div");
      row.className = "flex items-center justify-between gap-3";

      const left = document.createElement("div");
      left.className = "flex items-center gap-2 min-w-0";

      const dot = document.createElement("span");
      dot.className = "inline-block w-2.5 h-2.5 rounded-full shrink-0";
      dot.style.backgroundColor = colors[i] || "rgba(148,163,184,0.7)";

      const text = document.createElement("span");
      text.className = "truncate";
      text.textContent = label;

      left.appendChild(dot);
      left.appendChild(text);

      const right = document.createElement("div");
      right.className = "shrink-0 text-slate-500";
      right.textContent = `${pct}%`;

      row.appendChild(left);
      row.appendChild(right);
      container.appendChild(row);
    });
  }

  function hashColor(str) {
    const source = String(str || "unknown").toLowerCase();
    let hash = 0;
    for (let i = 0; i < source.length; i++) hash = (hash * 31 + source.charCodeAt(i)) >>> 0;
    const r = 80 + (hash & 0x7F);
    const g = 80 + ((hash >> 7) & 0x7F);
    const b = 80 + ((hash >> 14) & 0x7F);
    return `rgb(${r}, ${g}, ${b})`;
  }

  function mediaColor(label) {
    const key = String(label || "unknown").toLowerCase().trim();
    const map = {
      movie: "#3B82F6",
      serie: "#10B981",
      episode: "#10B981",
      show: "#10B981",
      other: "#EF4444",
      unknown: "#94A3B8"
    };
    if (map[key]) return map[key];
    if (key.includes("serie") || key.includes("episode") || key.includes("show")) return map.serie;
    if (key.includes("movie") || key.includes("film")) return map.movie;
    return hashColor(key);
  }

  async function initCharts() {
    await waitForChart();

    const mediaTypes = Array.isArray(config.mediaTypes30d) ? config.mediaTypes30d : [];
    const serverUsage = Array.isArray(config.serverUsage30d) ? config.serverUsage30d : [];

    const mediaTypesEl = document.getElementById("chartMediaTypes");
    if (mediaTypesEl && mediaTypes.length) {
      const labels = mediaTypes.map((item) => item.label);
      const values = mediaTypes.map((item) => Number(item.plays || 0));
      const colors = labels.map(mediaColor);

      new Chart(mediaTypesEl.getContext("2d"), {
        type: "doughnut",
        data: {
          labels,
          datasets: [{ data: values, backgroundColor: colors, borderColor: "rgba(255,255,255,0.06)", borderWidth: 1 }]
        },
        options: doughnutOpts()
      });

      makeLegend(document.getElementById("legendMediaTypes"), labels, values, colors);
    }

    const serverUsageEl = document.getElementById("chartServerUsage");
    if (serverUsageEl && serverUsage.length) {
      const labels = serverUsage.map((item) => item.label);
      const values = serverUsage.map((item) => Number(item.plays || 0));
      const colors = labels.map(hashColor);

      new Chart(serverUsageEl.getContext("2d"), {
        type: "doughnut",
        data: {
          labels,
          datasets: [{ data: values, backgroundColor: colors, borderColor: "rgba(255,255,255,0.06)", borderWidth: 1 }]
        },
        options: doughnutOpts()
      });

      makeLegend(document.getElementById("legendPerServer"), labels, values, colors);
    }

    if (!config.dailyUrl) return;
    const data = await fetchJSON(config.dailyUrl);
    const labels = (data || []).map((item) => item.day);
    const plays = (data || []).map((item) => Number(item.plays || 0));
    const watch = (data || []).map((item) => hoursFromMs(item.watch_ms));

    const playsEl = document.getElementById("chartUserPlays");
    const watchEl = document.getElementById("chartUserWatch");
    if (!playsEl || !watchEl) return;

    new Chart(playsEl.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: config.playsLabel || "Plays",
          data: plays,
          tension: 0.4,
          fill: true,
          borderWidth: 2,
          pointRadius: 3,
          backgroundColor: "rgba(16,185,129,0.08)",
          borderColor: "rgba(16,185,129,1)"
        }]
      },
      options: baseLineOpts()
    });

    new Chart(watchEl.getContext("2d"), {
      type: "line",
      data: {
        labels,
        datasets: [{
          label: config.hoursLabel || "Hours",
          data: watch,
          tension: 0.4,
          fill: true,
          borderWidth: 2,
          pointRadius: 3,
          backgroundColor: "rgba(59,130,246,0.08)",
          borderColor: "rgba(59,130,246,1)"
        }]
      },
      options: baseLineOpts()
    });
  }

  initCharts().catch(console.error);
})();

(function () {
  const modal = document.getElementById("ipLookupModal");
  if (!modal) return;

  const configNode = document.getElementById("monitoring-user-detail-config");
  let messages = {};
  try {
    messages = JSON.parse(configNode ? configNode.textContent || "{}" : "{}");
  } catch (error) {
    messages = {};
  }

  const modalClose = document.getElementById("ipLookupModalClose");
  const modalSubtitle = document.getElementById("ipLookupModalSubtitle");

  const loadingBox = document.getElementById("ipLookupLoading");
  const errorBox = document.getElementById("ipLookupError");
  const contentBox = document.getElementById("ipLookupContent");

  const elIp = document.getElementById("ipLookupIp");
  const elLocation = document.getElementById("ipLookupLocation");
  const elIsp = document.getElementById("ipLookupIsp");
  const elTimezone = document.getElementById("ipLookupTimezone");
  const elOrg = document.getElementById("ipLookupOrg");
  const elAsn = document.getElementById("ipLookupAsn");
  const elCoords = document.getElementById("ipLookupCoords");
  const badges = document.getElementById("ipLookupBadges");

  const mapWrap = document.getElementById("ipLookupMapWrap");
  const noMap = document.getElementById("ipLookupNoMap");
  const mapFrame = document.getElementById("ipLookupMap");

  const triggerButtons = document.querySelectorAll(".js-ip-lookup");
  const dash = "-";

  function openModal() {
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function closeModal() {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    mapFrame.src = "";
  }

  function resetState(ip) {
    modalSubtitle.textContent = ip || dash;
    loadingBox.classList.remove("hidden");
    errorBox.classList.add("hidden");
    contentBox.classList.add("hidden");

    elIp.textContent = dash;
    elLocation.textContent = dash;
    elIsp.textContent = dash;
    elTimezone.textContent = dash;
    elOrg.textContent = dash;
    elAsn.textContent = dash;
    elCoords.textContent = dash;
    badges.innerHTML = "";

    mapWrap.classList.add("hidden");
    noMap.classList.remove("hidden");
    mapFrame.src = "";
  }

  function showError(message) {
    loadingBox.classList.add("hidden");
    contentBox.classList.add("hidden");
    errorBox.textContent = message || messages.unableIp || "Unable to load IP details.";
    errorBox.classList.remove("hidden");
  }

  function setText(el, value, fallback = dash) {
    el.textContent = (value === null || value === undefined || value === "") ? fallback : value;
  }

  function addBadge(label, tone = "slate") {
    const palette = {
      slate: "border-slate-700 bg-slate-800 text-slate-200",
      emerald: "border-emerald-800 bg-emerald-950/50 text-emerald-300",
      amber: "border-amber-800 bg-amber-950/50 text-amber-300",
      rose: "border-rose-800 bg-rose-950/50 text-rose-300",
      sky: "border-sky-800 bg-sky-950/50 text-sky-300",
    };

    const span = document.createElement("span");
    span.className = "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium " + (palette[tone] || palette.slate);
    span.textContent = label;
    badges.appendChild(span);
  }

  async function loadIpDetails(ip) {
    resetState(ip);
    openModal();

    try {
      const res = await fetch(`/api/monitoring/ip_lookup?ip=${encodeURIComponent(ip)}`, {
        cache: "no-cache",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      });

      const data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      loadingBox.classList.add("hidden");
      errorBox.classList.add("hidden");
      contentBox.classList.remove("hidden");

      setText(elIp, data.ip);
      setText(elLocation, data.display_name);
      setText(elIsp, data.isp);
      setText(elTimezone, data.timezone);
      setText(elOrg, data.org);
      setText(elAsn, data.asn || data.asname);

      if (data.lat !== null && data.lat !== undefined && data.lon !== null && data.lon !== undefined) {
        setText(elCoords, `${data.lat}, ${data.lon}`);
      } else {
        setText(elCoords, null);
      }

      if (data.is_private) {
        addBadge(messages.privateIp || "Private IP", "amber");
      } else {
        addBadge(messages.publicIp || "Public IP", "emerald");
      }

      if (data.mobile) addBadge(messages.mobileNetwork || "Mobile network", "sky");
      if (data.proxy) addBadge(messages.proxyVpn || "Proxy/VPN", "rose");
      if (data.hosting) addBadge(messages.hosting || "Hosting", "amber");

      if (data.map_url) {
        mapFrame.src = data.map_url;
        mapWrap.classList.remove("hidden");
        noMap.classList.add("hidden");
      } else {
        mapWrap.classList.add("hidden");
        noMap.classList.remove("hidden");
      }
    } catch (err) {
      showError(messages.unableIp);
    }
  }

  triggerButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const ip = btn.dataset.ip || "";
      if (!ip) return;
      loadIpDetails(ip);
    });
  });

  if (modalClose) {
    modalClose.addEventListener("click", closeModal);
  }

  modal.addEventListener("click", (event) => {
    if (event.target === modal || (event.target.classList && event.target.classList.contains("bg-black/70"))) {
      closeModal();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });
})();
