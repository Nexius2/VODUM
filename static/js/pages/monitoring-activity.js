(() => {
  const configNode = document.getElementById("monitoring-activity-config");
  let config = {};
  try {
    config = JSON.parse(configNode ? configNode.textContent || "{}" : "{}");
  } catch (error) {
    config = {};
  }

  window.__vodumCharts = window.__vodumCharts || new Map();

  function keyFor(canvas) { return `${location.pathname}::${canvas.id}`; }

  function getOrCreate(canvas, factory) {
    const key = keyFor(canvas);
    const existing = window.__vodumCharts.get(key);
    if (existing) return existing;
    const created = factory();
    window.__vodumCharts.set(key, created);
    return created;
  }

  async function fetchJSON(url) {
    const res = await fetch(url, { cache: "no-cache" });
    if (!res.ok) throw new Error(`HTTP ${res.status} on ${url}`);
    return res.json();
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

  function baseOpts() {
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      normalized: true
    };
  }

  function toLabels(data, k) { return (data || []).map(x => x?.[k]); }

  function update(chart, labels, values) {
    chart.data.labels = labels;
    chart.data.datasets[0].data = values;
    chart.update("none");
  }

  function hashColor(str) {
    const s = String(str || "unknown").toLowerCase();
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    const r = 80 + (h & 0x7F);
    const g = 80 + ((h >> 7) & 0x7F);
    const b = 80 + ((h >> 14) & 0x7F);
    return `rgb(${r}, ${g}, ${b})`;
  }

  function mediaColor(label) {
    const k = String(label || "unknown").toLowerCase().trim();
    const MAP = {
      movie:  "#3B82F6",
      movies:  "#3B82F6",
      series:  "#10B981",
      serie:  "#10B981",
      show:   "#10B981",
      episode:"#10B981",
      tracks: "#A855F7",
      track:  "#A855F7",
      music:  "#A855F7",
      audio:  "#A855F7",
      photo:  "#F59E0B",
      image:  "#F59E0B",
      pictures:"#F59E0B",
      other:  "#EF4444",
      unknown:"#94A3B8"
    };
    if (MAP[k]) return MAP[k];
    if (k.includes("serie") || k.includes("episode") || k.includes("show")) return MAP.serie;
    if (k.includes("movie") || k.includes("film") || k.includes("video")) return MAP.movie;
    if (k.includes("track") || k.includes("music") || k.includes("audio")) return MAP.tracks;
    if (k.includes("photo") || k.includes("image") || k.includes("picture")) return MAP.photo;
    if (k.includes("unknown")) return MAP.unknown;
    if (k.includes("other")) return MAP.other;
    return hashColor(k);
  }

  function updateMediaTypes(chart, labels, values) {
    labels = labels || [];
    values = values || [];
    const pairs = labels.map((label, i) => ({ label, value: Number(values[i]) || 0 }))
      .filter(p => p.value > 0)
      .sort((a, b) => b.value - a.value);

    const sortedLabels = pairs.map(p => p.label);
    const sortedValues = pairs.map(p => p.value);

    chart.data.labels = sortedLabels;
    chart.data.datasets[0].data = sortedValues;
    chart.data.datasets[0].backgroundColor = sortedLabels.map(mediaColor);
    chart.data.datasets[0].borderColor = "#0B1220";
    chart.data.datasets[0].borderWidth = 2;
    chart.update("none");
  }

  function updatePerServer(chart, labels, values) {
    labels = labels || [];
    values = values || [];
    const pairs = labels.map((label, i) => ({ label, value: Number(values[i]) || 0 }))
      .filter(p => p.value > 0)
      .sort((a, b) => b.value - a.value);

    const sortedLabels = pairs.map(p => p.label);
    const sortedValues = pairs.map(p => p.value);

    chart.data.labels = sortedLabels;
    chart.data.datasets[0].data = sortedValues;
    chart.data.datasets[0].backgroundColor = sortedLabels.map(hashColor);
    chart.data.datasets[0].borderColor = "#0B1220";
    chart.data.datasets[0].borderWidth = 2;
    chart.update("none");
  }

  const doughnutPercentLabels = {
    id: "doughnutPercentLabels",
    afterDatasetsDraw(chart, args, pluginOptions) {
      const { ctx } = chart;
      const datasetIndex = (pluginOptions && pluginOptions.datasetIndex) ?? 0;
      const minPercent = (pluginOptions && pluginOptions.minPercent) ?? 5;

      const dataset = chart.data.datasets[datasetIndex];
      if (!dataset) return;

      const data = dataset.data || [];
      const total = data.reduce((a, b) => a + (Number(b) || 0), 0);
      if (!total) return;

      const meta = chart.getDatasetMeta(datasetIndex);
      if (!meta || !meta.data) return;

      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = "#E5E7EB";

      meta.data.forEach((arc, i) => {
        const value = Number(data[i]) || 0;
        if (!value) return;

        const percent = (value / total) * 100;
        if (percent < minPercent) return;

        const pos = arc.tooltipPosition();
        const fontSize = Math.max(10, Math.min(14, chart.width / 40));
        ctx.font = `600 ${fontSize}px system-ui, -apple-system, Segoe UI, Roboto, sans-serif`;
        ctx.fillText(`${percent.toFixed(0)}%`, pos.x, pos.y);
      });

      ctx.restore();
    }
  };

  function manualResize(chart, canvas) {
    if (!chart || !canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;

    const w = parent.clientWidth;
    const h = parent.clientHeight;
    if (!w || !h) return;

    // Chart.js owns the backing-store size and applies devicePixelRatio.
    // Writing canvas.width manually here made mobile charts render at roughly
    // half the available CSS width on high-density screens.
    try { chart.resize(w, h); chart.update("none"); } catch (_) {}
  }

  function manualResizeAll(list) {
    requestAnimationFrame(() => {
      list.forEach(({chart, canvas}) => manualResize(chart, canvas));
      setTimeout(() => list.forEach(({chart, canvas}) => manualResize(chart, canvas)), 250);
    });
  }

  let renderToken = 0;

  async function initOrUpdate(root = document) {
    const picker     = root.querySelector?.("#rangePicker")      || document.getElementById("rangePicker");
    const elActivity = root.querySelector?.("#chartActivity")    || document.getElementById("chartActivity");
    const elMedia    = root.querySelector?.("#chartMediaTypes")  || document.getElementById("chartMediaTypes");
    const elServer   = root.querySelector?.("#chartPerServer")   || document.getElementById("chartPerServer");
    const elWeekday  = root.querySelector?.("#chartWeekday")     || document.getElementById("chartWeekday");
    if (!picker || !elActivity || !elMedia || !elServer || !elWeekday) return;

    await waitForChart();

    const chartActivity = getOrCreate(elActivity, () => new Chart(elActivity.getContext("2d"), {
      type: "line",
      data: { labels: [], datasets: [{ label: config.sessionsLabel || "Sessions", data: [], tension: 0.25 }] },
      options: {
        ...baseOpts(),
        interaction: { mode: "nearest", intersect: true },
        elements: { point: { radius: 3, hoverRadius: 6, hitRadius: 12 } },
        plugins: {
          legend: { display: true },
          tooltip: {
            enabled: true,
            callbacks: { label: (ctx) => `${config.sessionsLabel || "Sessions"}: ${ctx.parsed?.y ?? (Number(ctx.raw) || 0)}` }
          }
        },
        scales: { y: { beginAtZero: true } }
      }
    }));

    const chartMedia = getOrCreate(elMedia, () => new Chart(elMedia.getContext("2d"), {
      type: "doughnut",
      data: { labels: [], datasets: [{ label: config.sessionsLabel || "Sessions", data: [], backgroundColor: [], borderColor: "#0B1220", borderWidth: 2 }] },
      options: {
        ...baseOpts(),
        cutout: "70%",
        plugins: {
          legend: { position: "top" },
          tooltip: { enabled: true },
          doughnutPercentLabels: { datasetIndex: 0, minPercent: 5 }
        }
      },
      plugins: [doughnutPercentLabels]
    }));

    const chartServer = getOrCreate(elServer, () => new Chart(elServer.getContext("2d"), {
      type: "doughnut",
      data: { labels: [], datasets: [{ label: config.sessionsLabel || "Sessions", data: [], backgroundColor: [], borderColor: "#0B1220", borderWidth: 2 }] },
      options: {
        ...baseOpts(),
        cutout: "70%",
        plugins: {
          legend: { position: "top" },
          tooltip: { enabled: true },
          doughnutPercentLabels: { datasetIndex: 0, minPercent: 6 }
        }
      },
      plugins: [doughnutPercentLabels]
    }));

    const chartWeekday = getOrCreate(elWeekday, () => new Chart(elWeekday.getContext("2d"), {
      type: "bar",
      data: { labels: [], datasets: [{ label: config.sessionsLabel || "Sessions", data: [] }] },
      options: {
        ...baseOpts(),
        plugins: { legend: { display: true }, tooltip: { enabled: true } },
        scales: { y: { beginAtZero: true } }
      }
    }));

    manualResizeAll([
      { chart: chartActivity, canvas: elActivity },
      { chart: chartMedia,    canvas: elMedia },
      { chart: chartServer,   canvas: elServer },
      { chart: chartWeekday,  canvas: elWeekday }
    ]);

    const token = ++renderToken;
    const range = picker.value || "7d";

    const [a, m, s, w] = await Promise.all([
      fetchJSON(`/api/monitoring/activity?range=${encodeURIComponent(range)}`),
      fetchJSON(`/api/monitoring/media_types?range=${encodeURIComponent(range)}`),
      fetchJSON(`/api/monitoring/per_server?range=${encodeURIComponent(range)}`),
      fetchJSON(`/api/monitoring/weekday?range=${encodeURIComponent(range)}`)
    ]);
    if (token !== renderToken) return;

    update(chartActivity, toLabels(a, "day"), toLabels(a, "sessions"));
    updateMediaTypes(chartMedia, toLabels(m, "media_type"), toLabels(m, "sessions"));
	const serverLabels = toLabels(s, "server_name") || [];
	const serverValues = toLabels(s, "sessions") || [];

	const activeServers = serverValues.filter(v => Number(v) > 0);

	const perServerBlock = document.getElementById("perServerBlock");

	const donutGrid = document.getElementById("donutGrid");

	if (activeServers.length <= 1) {
	  if (perServerBlock) perServerBlock.style.display = "none";
	  // ✅ Media types prend toute la place
	  if (donutGrid) donutGrid.classList.remove("md:grid-cols-2");
	} else {
	  if (perServerBlock) perServerBlock.style.display = "";
	  // ✅ On remet 2 colonnes
	  if (donutGrid && !donutGrid.classList.contains("md:grid-cols-2")) {
		donutGrid.classList.add("md:grid-cols-2");
	  }
	  updatePerServer(chartServer, serverLabels, serverValues);
	}
	manualResizeAll([{ chart: chartMedia, canvas: elMedia }]);



    const names = (Array.isArray(config.weekdayNames) ? config.weekdayNames : []);
    chartWeekday.data.labels = (w || []).map(x => names[x.weekday] ?? String(x.weekday));
    chartWeekday.data.datasets[0].data = (w || []).map(x => x.sessions);
    chartWeekday.update("none");

    manualResizeAll([
      { chart: chartActivity, canvas: elActivity },
      { chart: chartMedia,    canvas: elMedia },
      { chart: chartServer,   canvas: elServer },
      { chart: chartWeekday,  canvas: elWeekday }
    ]);

    if (!picker.__vodumBound) {
      picker.__vodumBound = true;
      picker.addEventListener("change", () => initOrUpdate(document).catch(console.error), { passive: true });
    }
  }

  initOrUpdate(document).catch(console.error);
})();
