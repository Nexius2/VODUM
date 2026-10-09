(() => {
  const configNode = document.getElementById("monitoring-servers-config");
  let config = {};
  try {
    config = JSON.parse(configNode ? configNode.textContent || "{}" : "{}");
  } catch (error) {
    config = {};
  }

  function waitForChart(maxMs = 8000) {
    const start = Date.now();

    return new Promise((resolve, reject) => {
      const tick = () => {
        if (window.Chart) {
          resolve();
          return;
        }

        if (Date.now() - start > maxMs) {
          reject(new Error("Chart.js not loaded"));
          return;
        }

        setTimeout(tick, 50);
      };

      tick();
    });
  }

  const picker = document.getElementById("serversRangePicker");
  if (picker) {
    picker.addEventListener("change", () => {
      const base = config.serversUrl || "/monitoring?tab=servers";
      const sep = base.includes("?") ? "&" : "?";
      window.location.href = `${base}${sep}range=${encodeURIComponent(picker.value || "7d")}`;
    });
  }

  async function renderServersCharts() {
    await waitForChart();

    const arr = config.arr || {};
    ['sonarr', 'radarr'].forEach(provider => {
      const instances = (arr.servers || []).filter(s => s.type === provider);
      const rows = arr.days || [];
      const days = [...new Set(rows.map(r => r.day))].sort();
      [['availability', config.arrAvailabilityLabel], ['queue', config.arrQueueLabel]].forEach(([metric, label]) => {
        const canvas = document.getElementById(`arr-${metric}-${provider}`);
        if (!canvas) return;
        const field = metric === 'queue' ? 'queue_count' : metric;
        new Chart(canvas, {type:'line', data:{labels:days, datasets:instances.map((server,index) => ({
          label:server.name + ' · ' + label,
          data:days.map(day => {const row=rows.find(r=>r.day===day && String(r.server_id)===String(server.id)); return row ? row[field] : null;}),
          borderColor:['#38bdf8','#a78bfa','#fb7185','#34d399'][index%4], tension:0.2, spanGaps:false
        }))}, options:{responsive:true, scales:{y:{beginAtZero:true, ...(metric==='availability' ? {max:100} : {})}}}});
      });
    });
    const details = Array.isArray(config.details) ? config.details : [];
    const sessionsDay = Array.isArray(config.sessionsDay) ? config.sessionsDay : [];
    const mediaTypes = Array.isArray(config.mediaTypes) ? config.mediaTypes : [];

    const serverNames = new Map(
      details.map((s) => [
        String(s.server_id),
        s.name || (config.serverLabel || "Server") + ` ${s.server_id}`
      ])
    );

    const days = [...new Set(sessionsDay.map((r) => String(r.day || "")).filter(Boolean))].sort();
    const serverIds = [...new Set(sessionsDay.map((r) => String(r.server_id || "")).filter(Boolean))].sort();

    const sessionsByDayServer = new Map();
    sessionsDay.forEach((r) => {
      sessionsByDayServer.set(`${r.day}|${r.server_id}`, Number(r.sessions || 0));
    });

    const datasetsSessions = serverIds.map((serverId) => ({
      label: serverNames.get(serverId) || (config.serverLabel || "Server") + ` ${serverId}`,
      data: days.map((day) => sessionsByDayServer.get(`${day}|${serverId}`) || 0),
      tension: 0.25,
      borderWidth: 2,
      pointRadius: 2,
      pointHoverRadius: 5,
      hitRadius: 10
    }));

    const sessionsCtx = document.getElementById("chartServersSessionsDay")?.getContext("2d");
    if (sessionsCtx) {
      new Chart(sessionsCtx, {
        type: "line",
        data: {
          labels: days,
          datasets: datasetsSessions
        },
        options: {
          responsive: true,
          interaction: {
            mode: "nearest",
            intersect: true
          },
          plugins: {
            tooltip: {
              callbacks: {
                label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}`
              }
            }
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: {
                precision: 0
              }
            }
          }
        }
      });
    }

    const typeList = [...new Set(mediaTypes.map((r) => String(r.media_type || "unknown")))].sort();
    const typeSum = new Map(typeList.map((type) => [type, 0]));

    mediaTypes.forEach((r) => {
      const type = String(r.media_type || "unknown");
      typeSum.set(type, (typeSum.get(type) || 0) + Number(r.sessions || 0));
    });

    const mediaCtx = document.getElementById("chartServersMediaTypes")?.getContext("2d");
    if (mediaCtx) {
      new Chart(mediaCtx, {
        type: "bar",
        data: {
          labels: typeList,
          datasets: [{
            label: config.sessionsLabel || "Sessions",
            data: typeList.map((type) => typeSum.get(type) || 0)
          }]
        },
        options: {
          responsive: true,
          interaction: {
            mode: "nearest",
            intersect: true
          },
          plugins: {
            tooltip: {
              callbacks: {
                label: (ctx) => `${config.sessionsLabel || "Sessions"}: ${ctx.parsed.y}`
              }
            }
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: {
                precision: 0
              }
            }
          }
        }
      });
    }
  }

  renderServersCharts().catch(console.error);
})();
