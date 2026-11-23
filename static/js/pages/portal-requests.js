(function () {
  const feedback = document.getElementById('request-feedback');
  if (!feedback) return;
  const messages = JSON.parse(feedback.dataset.messages);
  const jobsPanel = document.getElementById('request-jobs');
  const jobList = jobsPanel?.querySelector('[data-job-list]');
  if (jobsPanel) messages.portal_requests_queued = jobsPanel.dataset.queued;
  let hasActiveJobs = jobsPanel?.dataset.active === '1';
  let hasTrackedJobs = jobsPanel?.dataset.tracking === '1';
  let pollPending = false;
  let refreshRequested = false;
  let jobTimer;
  let lastJobs;
  const FINAL_SEERR_STATES = ['declined', 'failed', 'available', 'removed'];

  function scheduleJobsPoll() {
    clearTimeout(jobTimer);
    if (document.hidden) return;
    // Jobs still running poll quickly; a submitted Seerr request only needs an occasional look.
    if (hasActiveJobs) jobTimer = setTimeout(refreshJobs, 2500);
    else if (hasTrackedJobs) jobTimer = setTimeout(refreshJobs, 60000);
  }

  function badge(state, text) {
    const span = document.createElement('span');
    span.className = 'portal-request-badge mt-1';
    span.dataset.state = state;
    span.textContent = text;
    return span;
  }

  function renderJob(job) {
    const row = document.createElement('li');
    row.className = 'rounded-lg bg-slate-950 px-3 py-2';
    const title = document.createElement('strong');
    title.textContent = job.title;
    row.append(title);
    const details = [];
    if (job.is_4k) details.push(messages.portal_requests_badge_4k);
    if (Array.isArray(job.seasons) && job.seasons.length) details.push(`${messages.portal_requests_seasons_summary} ${job.seasons.join(', ')}`);
    if (details.length) {
      const detail = document.createElement('span');
      detail.className = 'ml-2 text-xs text-slate-400';
      detail.textContent = details.join(' · ');
      row.append(detail);
    }
    const status = document.createElement('span');
    status.className = 'block text-slate-300';
    status.textContent = job.status === 'done'
      ? messages[job.result] || messages.portal_requests_unavailable
      : job.status === 'queued' ? jobsPanel.dataset.queued : jobsPanel.dataset.checking;
    row.append(status);
    if (job.seerr_state && messages[`portal_requests_seerr_state_${job.seerr_state}`]) {
      row.append(badge(job.seerr_state, messages[`portal_requests_seerr_state_${job.seerr_state}`]));
    }
    return row;
  }

  async function refreshJobs() {
    clearTimeout(jobTimer);
    if (!jobList || document.hidden) return;
    if (pollPending) {
      refreshRequested = true;
      return;
    }
    pollPending = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(jobsPanel.dataset.statusUrl, {
        credentials: 'same-origin', signal: controller.signal, headers: {Accept: 'application/json'},
      });
      if (response.redirected || [401, 403, 404].includes(response.status)) {
        hasActiveJobs = false;
        return;
      }
      if (!response.ok) return;
      const {jobs} = await response.json();
      hasActiveJobs = jobs.some((job) => job.status !== 'done');
      hasTrackedJobs = jobs.some((job) => job.seerr_state && !FINAL_SEERR_STATES.includes(job.seerr_state));
      const snapshot = JSON.stringify(jobs);
      if (lastJobs === snapshot) return;
      lastJobs = snapshot;
      jobsPanel.hidden = jobs.length === 0;
      jobList.replaceChildren(...jobs.map(renderJob));
    } catch (_) {
      // Keep the last known job state and try again on the next visible poll.
    } finally {
      clearTimeout(timeout);
      pollPending = false;
      if (refreshRequested) {
        refreshRequested = false;
        refreshJobs();
      } else {
        scheduleJobsPoll();
      }
    }
  }

  document.addEventListener('visibilitychange', () => {
    clearTimeout(jobTimer);
    if (!document.hidden && (hasActiveJobs || hasTrackedJobs)) refreshJobs();
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted && jobsPanel) refreshJobs();
  });
  scheduleJobsPoll();
  const progressDialog = document.getElementById('request-progress-dialog');
  const progressTitle = document.getElementById('request-progress-title');
  const progressBody = document.getElementById('request-progress-body');
  let progressOwner = null;
  function startProgress(form, source) {
    if (progressOwner) return false;
    progressOwner = form;
    progressTitle.textContent = form.dataset.working;
    const content = source.cloneNode(true);
    content.hidden = false;
    content.removeAttribute('role');
    progressBody.replaceChildren(content);
    progressDialog.showModal();
    progressTitle.focus();
    return true;
  }
  function stopProgress(form) {
    if (progressOwner !== form) return;
    progressDialog.close();
    progressBody.replaceChildren();
    progressOwner = null;
  }
  progressDialog.addEventListener('cancel', (event) => event.preventDefault());

  // Season picker for Seerr series: every season not yet available is preselected.
  const seasonsDialog = document.getElementById('request-seasons-dialog');
  const seasonsForm = document.getElementById('request-seasons-form');
  const seasonsList = seasonsDialog?.querySelector('[data-seasons-list]');
  const seasonsAll = seasonsDialog?.querySelector('[data-seasons-all]');
  const seasonsError = seasonsDialog?.querySelector('[data-seasons-error]');
  function seasonBoxes() {
    return [...seasonsList.querySelectorAll('input[type="checkbox"]:not(:disabled)')];
  }
  function syncSeasonsAll() {
    const boxes = seasonBoxes();
    seasonsAll.checked = boxes.length > 0 && boxes.every((box) => box.checked);
    seasonsAll.disabled = boxes.length === 0;
  }
  seasonsAll?.addEventListener('change', () => {
    seasonBoxes().forEach((box) => { box.checked = seasonsAll.checked; });
  });
  seasonsList?.addEventListener('change', syncSeasonsAll);
  seasonsDialog?.querySelector('[data-seasons-cancel]').addEventListener('click', () => seasonsDialog.close('cancel'));
  function renderSeasons(seasons) {
    seasonsList.replaceChildren(...seasons.map((season) => {
      const label = document.createElement('label');
      const box = document.createElement('input');
      box.type = 'checkbox'; box.value = String(season.number);
      box.className = 'rounded border-slate-600 bg-slate-950';
      box.checked = season.requestable; box.disabled = !season.requestable;
      if (!season.requestable) label.dataset.disabled = '';
      const text = document.createElement('span');
      // Seerr may name a season by its bare number; the portal always says "Season N".
      text.textContent = `${messages.portal_requests_season} ${season.number}`;
      if (season.name && season.name !== String(season.number) && !/^season\s+\d+$/i.test(season.name)) {
        text.textContent += ` · ${season.name}`;
      }
      if (season.episodes) text.textContent += ` · ${season.episodes} ${messages.portal_requests_episodes}`;
      label.append(box, text);
      if (season.status && messages[`portal_requests_badge_${season.status}`]) {
        label.append(badge(season.status, messages[`portal_requests_badge_${season.status}`]));
      }
      return label;
    }));
    syncSeasonsAll();
  }
  async function loadSeasons(form) {
    const url = new URL(form.dataset.seasonsUrl, window.location.href);
    const choice = form.querySelector('input[type="checkbox"][name="is_4k"]');
    if (choice) url.searchParams.set('is_4k', choice.checked ? '1' : '0');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal, headers: {Accept: 'application/json'}});
      if (response.redirected || !response.ok) return null;
      const data = await response.json();
      return Array.isArray(data.seasons) ? data : null;
    } catch (_) {
      return null;
    } finally {
      clearTimeout(timeout);
    }
  }
  // Resolves to the chosen season numbers, [] for "all" (list unavailable), or null when cancelled.
  function chooseSeasons(seasons) {
    if (!seasonsDialog || typeof seasonsDialog.showModal !== 'function') return Promise.resolve([]);
    renderSeasons(seasons);
    seasonsError.hidden = true;
    return new Promise((resolve) => {
      function finish(event) {
        seasonsForm.removeEventListener('submit', onSubmit);
        seasonsDialog.removeEventListener('close', onClose);
        resolve(event);
      }
      function onSubmit(event) {
        event.preventDefault();
        const chosen = seasonBoxes().filter((box) => box.checked).map((box) => Number(box.value));
        if (!chosen.length) {
          seasonsError.textContent = messages.portal_requests_seasons_none_selected;
          seasonsError.hidden = false;
          return;
        }
        seasonsDialog.close('confirm');
        finish(chosen);
      }
      function onClose() { finish(null); }
      seasonsForm.addEventListener('submit', onSubmit);
      seasonsDialog.addEventListener('close', onClose);
      seasonsDialog.showModal();
      seasonsDialog.querySelector('h2').focus();
    });
  }
  // TVDB series picker for titles Seerr cannot map to TVDB. Resolves to the TVDB id or null when cancelled.
  const tvdbDialog = document.getElementById('request-tvdb-dialog');
  const tvdbForm = document.getElementById('request-tvdb-form');
  const tvdbList = tvdbDialog?.querySelector('[data-tvdb-list]');
  const tvdbError = tvdbDialog?.querySelector('[data-tvdb-error]');
  tvdbDialog?.querySelector('[data-tvdb-cancel]').addEventListener('click', () => tvdbDialog.close('cancel'));
  function chooseTvdb(candidates) {
    if (!tvdbDialog || typeof tvdbDialog.showModal !== 'function') return Promise.resolve(null);
    tvdbList.replaceChildren(...candidates.map((item) => {
      const label = document.createElement('label');
      label.className = 'flex items-center gap-3';
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'tvdb_choice'; radio.value = String(item.tvdb_id);
      label.append(radio);
      if (item.poster) {
        const img = document.createElement('img');
        img.src = item.poster; img.alt = ''; img.loading = 'lazy'; img.referrerPolicy = 'no-referrer';
        img.width = 40; img.height = 60; img.className = 'w-10 shrink-0 rounded object-cover';
        label.append(img);
      }
      const text = document.createElement('span');
      text.textContent = item.year ? `${item.title} (${item.year})` : item.title;
      label.append(text);
      return label;
    }));
    tvdbError.hidden = true;
    return new Promise((resolve) => {
      function finish(value) {
        tvdbForm.removeEventListener('submit', onSubmit);
        tvdbDialog.removeEventListener('close', onClose);
        resolve(value);
      }
      function onSubmit(event) {
        event.preventDefault();
        const picked = tvdbList.querySelector('input[type="radio"]:checked');
        if (!picked) {
          tvdbError.textContent = messages.portal_requests_tvdb_none_selected;
          tvdbError.hidden = false;
          return;
        }
        tvdbDialog.close('confirm');
        finish(picked.value);
      }
      function onClose() { finish(null); }
      tvdbForm.addEventListener('submit', onSubmit);
      tvdbDialog.addEventListener('close', onClose);
      tvdbDialog.showModal();
      tvdbDialog.querySelector('h2').focus();
    });
  }
  let timer;
  function close() {
    clearTimeout(timer);
    document.querySelectorAll('[data-request-toast]').forEach((toast) => toast.remove());
  }
  function show(result) {
    close();
    const toast = document.createElement('div');
    toast.className = 'portal-request-toast';
    toast.dataset.requestToast = '';
    toast.dataset.tone = ['portal_requests_present', 'portal_requests_added'].includes(result) ? 'success' : (['portal_requests_pending', 'portal_requests_queued', 'portal_requests_seerr_awaiting_approval', 'portal_requests_seerr_nothing_to_request'].includes(result) ? 'info' : 'error');
    const text = document.createElement('span');
    text.textContent = messages[result] || messages.portal_requests_unavailable;
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = '×';
    button.setAttribute('aria-label', feedback.dataset.close);
    button.addEventListener('click', close);
    toast.append(text, button); feedback.append(toast);
    if (toast.dataset.tone !== 'error') timer = setTimeout(close, 10000);
  }
  document.querySelectorAll('[data-close-toast]').forEach((button) => button.addEventListener('click', close));
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') close(); });
  document.querySelectorAll('[data-media-search]').forEach((form) => {
    const button = form.querySelector('button');
    const label = button.textContent;
    const progress = form.querySelector('[data-search-progress]');
    function reset() {
      button.disabled = false; button.textContent = label;
      form.removeAttribute('aria-busy'); stopProgress(form);
      document.querySelectorAll('[data-search-results]').forEach((results) => { results.hidden = false; });
    }
    window.addEventListener('pageshow', reset);
    form.addEventListener('submit', (event) => {
      if (form.getAttribute('aria-busy') === 'true') { event.preventDefault(); return; }
      if (!startProgress(form, progress)) { event.preventDefault(); return; }
      close(); button.disabled = true; button.textContent = form.dataset.working;
      form.setAttribute('aria-busy', 'true');
      document.querySelectorAll('[data-search-results]').forEach((results) => { results.hidden = true; });
    });
  });
  document.querySelectorAll('[data-media-request]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (form.getAttribute('aria-busy') === 'true') return;
      const button = form.querySelector('button[type="submit"], button:not([type])');
      const label = button.textContent;
      const progress = form.querySelector('[data-request-progress]');
      if (!startProgress(form, progress)) return;
      close();
      button.disabled = true; button.textContent = form.dataset.working;
      form.setAttribute('aria-busy', 'true');
      try {
        const body = new FormData(form);
        if (form.dataset.seasonsUrl) {
          const data = await loadSeasons(form);
          const seasons = data && data.seasons;
          const tvdb = (data && data.tvdb) || {};
          if (data === null) {
            show('portal_requests_seasons_unavailable');
          } else if (tvdb.state === 'none') {
            show('portal_requests_seerr_tvdb_unresolved');
            return;
          } else {
            stopProgress(form);
            if (tvdb.state === 'choose' && Array.isArray(tvdb.candidates) && tvdb.candidates.length) {
              const tvdbId = await chooseTvdb(tvdb.candidates);
              if (tvdbId === null) return;
              body.set('tvdb_id', tvdbId);
            }
            const chosen = await chooseSeasons(seasons);
            if (chosen === null) return;
            if (chosen.length) body.set('seasons', chosen.join(','));
            if (!startProgress(form, progress)) return;
          }
        }
        const response = await fetch(form.action, {method: 'POST', body, credentials: 'same-origin', headers: {Accept: 'application/json'}});
        if (response.redirected) throw new Error('Session unavailable');
        const data = await response.json();
        stopProgress(form);
        if (response.status === 202 && data.job_id) {
          hasActiveJobs = true;
          refreshJobs();
        }
        show(data.result || 'portal_requests_unavailable');
      } catch (_) {
        console.error("[vodum] portal media request failed");
        stopProgress(form);
        show('portal_requests_unavailable');
      } finally {
        stopProgress(form);
        button.disabled = false; button.textContent = label;
        form.removeAttribute('aria-busy');
      }
    });
  });
})();
