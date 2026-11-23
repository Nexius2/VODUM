(() => {
  const root = document.querySelector("[data-location-map]");
  if (!root) return;

  const wrap = (value) => ((value + 180) % 360 + 360) % 360 - 180;
  const basemap = fetch(root.dataset.basemap)
    .then((response) => {
      if (!response.ok) throw new Error("Basemap unavailable");
      return response.json();
    })
    .then((shapes) => shapes.map((shape) => {
      const path = new Path2D();
      const polygons = shape.type === "Polygon" ? [shape.coordinates] : shape.coordinates;
      for (const polygon of polygons) {
        for (const ring of polygon) {
          ring.forEach(([longitude, latitude], index) => {
            if (index === 0) path.moveTo(longitude, -latitude);
            else path.lineTo(longitude, -latitude);
          });
          path.closePath();
        }
      }
      return path;
    }))
    .catch(() => []);
  let view = null;
  let world = false;
  let dispose = () => {};
  let selectedGroup = new Set();
  let selectedGroupLabel = "";

  try {
    const saved = JSON.parse(sessionStorage.getItem("vodum-location-view"));
    sessionStorage.removeItem("vodum-location-view");
    const frame = saved?.view;
    world = saved?.world === true;
    if (frame && Number.isFinite(frame.scale) && frame.scale > 0
        && Number.isFinite(frame.longitude) && Number.isFinite(frame.latitude)) view = frame;
  } catch {}

  function rememberView() {
    try {
      if (view || world) sessionStorage.setItem("vodum-location-view", JSON.stringify({ view, world }));
    } catch {}
  }
  root.closest("section").addEventListener("submit", rememberView);
  document.querySelector("[data-location-heat]").addEventListener("click", rememberView);

  function fitMap(points, width, height) {
    if (!points.length) {
      return { longitude: 0, latitude: 0, scale: Math.min(width / 370, height / 185) };
    }
    const longitudes = points.map(({ longitude }) => longitude).sort((a, b) => a - b);
    let largestGap = -1;
    let west = longitudes[0];
    longitudes.forEach((longitude, index) => {
      const next = longitudes[index + 1] ?? longitudes[0] + 360;
      if (next - longitude > largestGap) {
        largestGap = next - longitude;
        west = next;
      }
    });
    let south = 90;
    let north = -90;
    for (const { latitude } of points) {
      south = Math.min(south, latitude);
      north = Math.max(north, latitude);
    }
    const span = 360 - largestGap;
    return {
      longitude: wrap(west + span / 2),
      latitude: (north + south) / 2,
      scale: Math.min(width * 0.78 / Math.max(span, 12), height * 0.74 / Math.max(north - south, 9)),
    };
  }

  function cluster(entries, project) {
    const cell = 30;
    const grid = new Map();
    for (const entry of entries) {
      const [x, y] = project(entry);
      const column = Math.floor(x / cell);
      const row = Math.floor(y / cell);
      let group;
      for (let dx = -1; dx <= 1 && !group; dx += 1) {
        for (let dy = -1; dy <= 1 && !group; dy += 1) {
          const candidates = grid.get([column + dx, row + dy].join(":")) || [];
          group = candidates.find((item) => Math.hypot(x - item.x, y - item.y) < cell);
        }
      }
      if (!group) {
        group = { x, y, members: [] };
        const key = [column, row].join(":");
        if (!grid.has(key)) grid.set(key, []);
        grid.get(key).push(group);
      }
      group.members.push(entry);
    }
    return [...grid.values()].flat();
  }

  function drawHeat(context, groups, scale) {
    const radius = Math.max(18, Math.min(54, 20 + Math.log2(1 + scale) * 6));
    context.save();
    context.globalCompositeOperation = "screen";
    for (const { x, y, members } of groups) {
      const strength = Math.min(1, 0.22 + Math.log2(members.length) * 0.17);
      const glow = context.createRadialGradient(x, y, 0, x, y, radius);
      glow.addColorStop(0, "rgba(78,236,255," + strength + ")");
      glow.addColorStop(0.45, "rgba(70,95,255," + strength * 0.75 + ")");
      glow.addColorStop(0.75, "rgba(134,77,255," + strength * 0.42 + ")");
      glow.addColorStop(1, "transparent");
      context.fillStyle = glow;
      context.fillRect(x - radius, y - radius, radius * 2, radius * 2);
    }
    context.restore();
  }

  function initMap() {
    dispose();
    const map = root.querySelector(".location-map");
    const stats = root.querySelector(".location-stats");
    if (!map || !stats) return;
    document.querySelector("#location-stats").replaceChildren(stats);
    const countries = document.querySelector("[data-location-countries]");
    const availableCountries = JSON.parse(root.querySelector("[data-map-countries]").dataset.mapCountries);
    const names = new Intl.DisplayNames([document.documentElement.lang || "en"], { type: "region" });
    const selectedCountry = countries.value;
    countries.replaceChildren(countries.options[0], ...availableCountries
      .map((code) => new Option(names.of(code), code, false, code === selectedCountry))
      .sort((a, b) => a.text.localeCompare(b.text, document.documentElement.lang || "en")));
    const canvas = map.querySelector("canvas");
    const layer = map.querySelector(".location-map-points");
    const panel = root.querySelector(".location-group");
    const closeGroup = panel.querySelector("[data-group-close]");
    const entries = [...layer.querySelectorAll("[data-lat]")].map((detail) => ({
      latitude: Number(detail.dataset.lat),
      longitude: Number(detail.dataset.lon),
      detail,
    })).filter(({ latitude, longitude }) =>
      Number.isFinite(latitude) && Number.isFinite(longitude) && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180);
    const heat = root.dataset.heat === "1";
    let current;
    let animation;
    let dragFrame;
    let shapes = [];
    let drag;
    const pointers = new Map();
    let ready = false;
    const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

    function loadAvatars(container) {
      for (const img of container.querySelectorAll("img[data-location-avatar]:not([src])")) {
        img.loading = "lazy";
        img.addEventListener("load", () => { img.style.visibility = "visible"; }, { once: true });
        img.hidden = false;
        img.style.visibility = "hidden";
        img.src = img.dataset.locationAvatar;
      }
    }

    function updateGroupPanel() {
      const list = panel.querySelector(".location-group-list");
      const members = entries.filter(({ detail }) => selectedGroup.has(detail.dataset.identity));
      if (!members.length) selectedGroup.clear();
      panel.hidden = !members.length;
      map.parentElement.classList.toggle("has-group", !panel.hidden);
      panel.querySelector("[data-group-count]").textContent = "(" + members.length + ")";
      list.replaceChildren(...members.map(({ detail }) => {
        const card = detail.cloneNode(true);
        card.hidden = false;
        for (const img of card.querySelectorAll("img[data-location-avatar]")) img.removeAttribute("src");
        return card;
      }));
      loadAvatars(list);
    }

    closeGroup.addEventListener("click", () => {
      selectedGroup.clear();
      updateGroupPanel();
      requestAnimationFrame(() => {
        const buttons = [...layer.querySelectorAll('[data-state="cluster"]')];
        const previous = buttons.find((button) => button.getAttribute("aria-label") === selectedGroupLabel);
        (previous || buttons[0] || map.querySelector('[data-map-action="fit"]'))?.focus();
      });
    });
    if (selectedGroup.size) updateGroupPanel();

    function draw(frame, moving = false) {
      const { clientWidth: width, clientHeight: height } = map;
      if (!width || !height) return;
      current = frame;
      const density = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * density);
      canvas.height = Math.round(height * density);
      const context = canvas.getContext("2d");
      context.scale(density, density);
      const x = (longitude) => width / 2 + (longitude - frame.longitude) * frame.scale;
      const y = (latitude) => height / 2 - (latitude - frame.latitude) * frame.scale;
      context.fillStyle = "#21364e";
      context.strokeStyle = "#435870";
      for (const shift of [-360, 0, 360]) {
        if (x(180 + shift) < 0 || x(-180 + shift) > width) continue;
        context.save();
        context.translate(x(shift), y(0));
        context.scale(frame.scale, frame.scale);
        context.lineWidth = 0.7 / frame.scale;
        for (const path of shapes) {
          context.fill(path, "evenodd");
          context.stroke(path);
        }
        context.restore();
      }

      const groups = cluster(entries, (entry) => [
        width / 2 + wrap(entry.longitude - frame.longitude) * frame.scale,
        y(entry.latitude),
      ]);
      layer.replaceChildren();
      if (heat) {
        drawHeat(context, groups, frame.scale);
        return;
      }
      for (const { x: left, y: top, members } of groups) {
        if (left < 0 || top < 0 || left > width || top > height) continue;
        const marker = document.createElement("div");
        marker.className = "location-map-marker";
        marker.style.left = left + "px";
        marker.style.top = top + "px";
        marker.classList.toggle("location-map-marker-right", left > width / 2);
        marker.classList.toggle("location-map-marker-top", top > height / 2);
        const dot = document.createElement("button");
        dot.type = "button";
        dot.dataset.state = members.length > 1 ? "cluster" : members[0].detail.dataset.state;
        dot.setAttribute("aria-label", members.map(({ detail }) => detail.querySelector("strong").textContent).join(", "));
        if (members.length > 1) {
          dot.textContent = members.length;
          dot.setAttribute("aria-controls", "location-group");
          dot.setAttribute("aria-expanded", String(!panel.hidden && members.every(
            ({ detail }) => selectedGroup.has(detail.dataset.identity)
          ) && selectedGroup.size === members.length));
          if (!moving) dot.addEventListener("click", () => {
            selectedGroup = new Set(members.map(({ detail }) => detail.dataset.identity));
            selectedGroupLabel = dot.getAttribute("aria-label");
            updateGroupPanel();
            render();
            closeGroup.focus({ preventScroll: true });
            if (matchMedia("(max-width: 760px)").matches) panel.scrollIntoView({ block: "nearest" });
          });
          marker.append(dot);
          layer.append(marker);
          continue;
        }
        if (moving) {
          marker.append(dot);
          layer.append(marker);
          continue;
        }
        const tooltip = document.createElement("div");
        tooltip.className = "location-map-tooltip";
        for (const { detail } of members) {
          detail.hidden = false;
          tooltip.append(detail);
        }
        const showAvatars = () => loadAvatars(tooltip);
        marker.addEventListener("pointerenter", showAvatars, { once: true });
        marker.addEventListener("focusin", showAvatars, { once: true });
        dot.addEventListener("click", () => {
          const link = tooltip.querySelector("a");
          if (link && !matchMedia("(hover: none)").matches) link.click();
          else dot.focus();
        });
        marker.append(dot, tooltip);
        layer.append(marker);
      }
    }

    function render(smooth = false) {
      if (!ready) return;
      cancelAnimationFrame(animation);
      const target = view || fitMap(world ? [] : entries, map.clientWidth, map.clientHeight);
      if (!smooth || !current || reducedMotion.matches) return draw(target);
      const start = current;
      const offset = wrap(target.longitude - start.longitude);
      const started = performance.now();
      const tick = (now) => {
        const step = Math.min(1, (now - started) / 200);
        const fraction = 1 - (1 - step) ** 3;
        draw({
          longitude: wrap(start.longitude + offset * fraction),
          latitude: start.latitude + (target.latitude - start.latitude) * fraction,
          scale: start.scale + (target.scale - start.scale) * fraction,
        }, step < 1);
        if (step < 1) animation = requestAnimationFrame(tick);
      };
      animation = requestAnimationFrame(tick);
    }

    function zoom(factor) {
      if (!current) return;
      const min = fitMap([], map.clientWidth, map.clientHeight).scale;
      view = { ...current, scale: Math.min(180, Math.max(min, current.scale * factor)) };
      world = false;
      render(true);
    }

    map.addEventListener("click", (event) => {
      const action = event.target.closest("[data-map-action]")?.dataset.mapAction;
      if (action === "in" || action === "out") zoom(action === "in" ? 1.6 : 1 / 1.6);
      if (action === "fit" || action === "world") {
        world = action === "world";
        view = null;
        render(true);
      }
    });
    map.addEventListener("wheel", (event) => {
      if (!event.deltaY || event.target.closest(".location-map-tooltip")) return;
      event.preventDefault();
      zoom(event.deltaY < 0 ? 1.35 : 1 / 1.35);
    }, { passive: false });
    function gesture() {
      const [first, second] = pointers.values();
      if (!first) return null;
      if (!second) return { ...first, distance: 0 };
      return {
        x: (first.x + second.x) / 2,
        y: (first.y + second.y) / 2,
        distance: Math.hypot(first.x - second.x, first.y - second.y),
      };
    }

    map.addEventListener("pointerdown", (event) => {
      if (!current || pointers.size >= 2 || event.button !== 0
          || event.target.closest("button, a, .location-map-tooltip")) return;
      cancelAnimationFrame(animation);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      drag = { ...gesture(), frame: view || current };
      map.setPointerCapture(event.pointerId);
    });
    map.addEventListener("pointermove", (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
      const next = gesture();
      const { frame } = drag;
      const { clientWidth: width, clientHeight: height } = map;
      const bounds = map.getBoundingClientRect();
      const min = fitMap([], width, height).scale;
      const scale = drag.distance
        ? Math.min(180, Math.max(min, frame.scale * next.distance / drag.distance))
        : frame.scale;
      const centerX = bounds.left + width / 2;
      const centerY = bounds.top + height / 2;
      view = {
        longitude: wrap(frame.longitude + (drag.x - centerX) / frame.scale - (next.x - centerX) / scale),
        latitude: Math.max(-90, Math.min(90,
          frame.latitude - (drag.y - centerY) / frame.scale + (next.y - centerY) / scale)),
        scale,
      };
      world = false;
      if (!dragFrame) dragFrame = requestAnimationFrame(() => {
        dragFrame = null;
        draw(view, true);
      });
    });
    map.addEventListener("lostpointercapture", (event) => {
      if (!pointers.delete(event.pointerId)) return;
      const remaining = gesture();
      drag = remaining ? { ...remaining, frame: view || current } : null;
      if (!drag && dragFrame) {
        cancelAnimationFrame(dragFrame);
        dragFrame = null;
      }
      if (!drag && view) render();
    });

    const observer = new ResizeObserver(() => render());
    observer.observe(map);
    basemap.then((data) => {
      if (!map.isConnected) return;
      shapes = data;
      ready = true;
      map.querySelector("[data-location-error]").hidden = Boolean(shapes.length);
      render();
    });
    dispose = () => {
      observer.disconnect();
      cancelAnimationFrame(animation);
      cancelAnimationFrame(dragFrame);
    };
  }

  initMap();
  root.addEventListener("htmx:afterSwap", initMap);
  root.addEventListener("htmx:beforeRequest", (event) => {
    if (root.querySelector(".location-map-marker:focus-within, .location-map-marker:hover")
        || root.querySelector(".location-map:active")) event.preventDefault();
  });
  root.addEventListener("htmx:beforeSwap", (event) => {
    if (root.querySelector(".location-map-marker:focus-within, .location-map-marker:hover")
        || root.querySelector(".location-group:focus-within, .location-group:hover")
        || root.querySelector(".location-map:active")) event.detail.shouldSwap = false;
  });

  const timeline = document.querySelector("[data-location-timeline]");
  if (!timeline) return;
  const slider = timeline.querySelector("input");
  const output = timeline.querySelector("output");
  const play = timeline.querySelector("[data-timeline-play]");
  const error = timeline.querySelector("[data-timeline-error]");
  const startTime = Number(slider.min);
  const endTime = Number(slider.max);
  const formatter = new Intl.DateTimeFormat(document.documentElement.lang || "en", {
    dateStyle: "short", timeStyle: "short",
  });
  let pending;
  let timer;
  let debounce;

  function showTime() {
    output.value = formatter.format(Number(slider.value) * 1000);
    slider.setAttribute("aria-valuetext", output.value);
  }

  function loadInstant() {
    pending?.abort();
    const request = new AbortController();
    pending = request;
    const url = new URL(window.location.href);
    url.searchParams.set("until", String(endTime));
    url.searchParams.set("at", Math.round(Number(slider.value)));
    root.setAttribute("aria-busy", "true");
    async function fetchPreparedInstant() {
      if (request.signal.aborted) throw new DOMException('Cancelled', 'AbortError');
      const response = await fetch(url, { headers: { "HX-Request": "true" }, signal: request.signal });
      if (!response.ok) throw new Error("Timeline unavailable");
      if (response.headers.get('X-VODUM-Statistics-Ready') === '0') {
        await response.text();
        let notice = root.querySelector('[data-timeline-preparing]');
        if (!notice) {
          notice = document.createElement('p');
          notice.dataset.timelinePreparing = '';
          notice.setAttribute('role', 'status');
          notice.className = 'text-sm text-slate-400';
          notice.textContent = root.dataset.statisticsPending;
          root.prepend(notice);
        }
        await new Promise(resolve => setTimeout(resolve, 5000));
        return fetchPreparedInstant();
      }
      return response.text();
    }
    fetchPreparedInstant()
      .then((html) => {
        if (request.signal.aborted) return;
        root.innerHTML = html;
        if (window.htmx) window.htmx.process(root);
        initMap();
        window.vodumRefreshBrowserDateTimes?.(root);
        history.replaceState(history.state, "", url);
        const heatLink = document.querySelector("[data-location-heat]");
        const heatUrl = new URL(heatLink.href);
        heatUrl.searchParams.set("at", url.searchParams.get("at"));
        heatUrl.searchParams.set("until", url.searchParams.get("until"));
        heatLink.href = heatUrl;
        document.querySelector('.location-filters [name="at"]').value = url.searchParams.get("at");
        error.hidden = true;
      })
      .catch(() => {
        if (!request.signal.aborted) {
          pause();
          error.hidden = false;
        }
      })
      .finally(() => {
        if (pending === request) {
          root.removeAttribute("aria-busy");
          pending = null;
        }
      });
  }

  function pause() {
    clearInterval(timer);
    timer = null;
    play.textContent = play.dataset.play;
    play.setAttribute("aria-pressed", "false");
  }

  play.addEventListener("click", () => {
    if (timer) return pause();
    clearTimeout(debounce);
    play.textContent = play.dataset.pause;
    play.setAttribute("aria-pressed", "true");
    if (Number(slider.value) >= endTime) slider.value = slider.min;
    showTime();
    loadInstant();
    timer = setInterval(() => {
      if (pending || document.hidden) return;
      const step = (endTime - startTime) / 60;
      slider.value = Math.min(endTime, Number(slider.value) + step);
      showTime();
      loadInstant();
      if (Number(slider.value) >= endTime) pause();
    }, 900);
  });
  slider.addEventListener("input", () => {
    pause();
    pending?.abort();
    showTime();
    clearTimeout(debounce);
    debounce = setTimeout(loadInstant, 160);
  });
  showTime();
  window.addEventListener("pagehide", () => {
    pause();
    clearTimeout(debounce);
    pending?.abort();
  });
})();
