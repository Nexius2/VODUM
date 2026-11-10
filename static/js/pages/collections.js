(() => {
  "use strict";
  const root = document.getElementById("collections-workspace");
  if (!root) return;
  const config = JSON.parse(document.getElementById("cl-config").textContent);
  const labels = JSON.parse(document.getElementById("cl-labels").textContent);
  const t = (key) => labels[key] || key;
  const $ = (selector) => root.querySelector(selector);
  const all = (selector) => [...root.querySelectorAll(selector)];
  const peopleDialog = $("#cl-people");
  const editor = $("#cl-editor"), preview = $("#cl-preview"), form = $("#cl-form");
  const deleteDialog = $("#cl-delete-confirm");
  const sourcesDialog = $("#cl-provider-sources");
  [editor, preview, peopleDialog, deleteDialog, sourcesDialog].forEach((dialog) => {
    const outside = (event) => {
      const bounds = dialog.getBoundingClientRect();
      return event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom);
    };
    let startedOutside = false;
    dialog.addEventListener('pointerdown', (event) => {startedOutside = outside(event);});
    dialog.addEventListener('click', (event) => {
      if (startedOutside && outside(event)) dialog.close();
      startedOutside = false;
    });
  });
  const field = (name) => form.elements.namedItem(name);
  const modelFor = (id) => config.catalog.find((item) => item.id === id);
  const libraryFor = (id) => config.libraries.find((item) => String(item.id) === String(id));
  const storageKey = "vodum.collections.drafts.v1";
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"}[char]));
  const uid = () => window.crypto.randomUUID ? window.crypto.randomUUID() : "draft-" + [...window.crypto.getRandomValues(new Uint8Array(16))].map((value) => value.toString(16).padStart(2, "0")).join("");
  let drafts = [], localDrafts = [], runs = [], collectionObjects = [], examplesVisible = false, step = 0, startStep = 0, editingId = null, duplicateLibrary = null, duplicateSource = null, feedbackTimer, refreshBusy = false, pendingSave = null, saveBusy = false, peopleInstance = null, peopleEditable = false, peopleVersion = 0;

  let attachedLibraryIds = new Set();
  let sharedSettings = config.settings;
  let settingsDirty = false;
  let activitySignature = '';
  const failedPortraits = new Set();
  function portrait(person) {
    const path = person.profile_path;
    const valid = typeof path === 'string' && /^\/[A-Za-z0-9_-]+\.(jpg|png|webp)$/.test(path) && !failedPortraits.has(path);
    return `<span class="cl-person-portrait" aria-hidden="true"><svg viewBox="0 0 40 56"><circle cx="20" cy="17" r="9"/><path d="M4 52v-8a16 16 0 0132 0v8z"/></svg>${valid ? `<img src="/api/collections/portrait?path=${encodeURIComponent(path)}" data-portrait-path="${escape(path)}" alt="" loading="lazy" decoding="async">` : ''}</span>`;
  }
  root.addEventListener('error',(event) => {
    const img = event.target;
    if (img instanceof HTMLImageElement && img.dataset.portraitPath) {failedPortraits.add(img.dataset.portraitPath);img.remove();}
  },true);
  function arrDetails(result) {
    const rows = result.arr_details || [];
    if (!rows.length) return (result.errors || []).some((key) => key.startsWith('collections.arr_media_failed:')) ? `<p class="cl-notice">${escape(t('arr_old_details_missing'))}</p>` : '';
    return rows.map((row) => `<div class="cl-arr-detail" data-severity="${escape(row.severity)}"><strong>${escape(row.title)}${row.tmdb_id ? ' · TMDb '+escape(row.tmdb_id) : ''}</strong><p>${escape(t(row.reason))}${row.server_name ? ' · '+escape(row.server_name) : ''} · ${escape(t('arr_stage.'+row.stage))}${row.http_status ? ' · HTTP '+escape(row.http_status) : ''}${row.error_type ? ' · '+escape(row.error_type) : ''}</p>${row.fields?.length ? `<small>${escape(t('arr_fields'))}: ${escape(row.fields.join(', '))}</small>` : ''}</div>`).join('');
  }
  function streamingDetails(result) {
    const providers = result.diagnostics?.providers || [];
    if (!providers.length) return '';
    const directKinds = ['platform_chart','worldwide_platform_chart','continent_platform_chart','worldwide_tmdb_streaming','continent_tmdb_streaming','country_tmdb_availability','country_tmdb_trending'];
    const fallbackKinds = ['justwatch_popularity','worldwide_tmdb_trending'];
    const hasCoverage = providers.some((row) => [...directKinds,...fallbackKinds].includes(row.source_kind));
    const coverage = result.diagnostics?.coverage || {
      direct: providers.filter((row) => directKinds.includes(row.source_kind) && row.count>0).length,
      fallback: providers.filter((row) => fallbackKinds.includes(row.source_kind) && row.count>0).length,
      failed: providers.filter((row) => row.state==='error').length,
    };
    const summary = hasCoverage ? `<p class="cl-muted">${escape(t('streaming_coverage').replace('{direct}',coverage.direct).replace('{fallback}',coverage.fallback).replace('{failed}',coverage.failed))}</p>${!coverage.direct && coverage.fallback ? `<p class="cl-notice">${escape(t('streaming_degraded'))}</p>` : ''}` : '';
    return `${summary}<div class="cl-provider-grid">${providers.map((row) => {
      const failures = [...(row.failures || []),...(row.failure ? [row.failure] : [])];
      return `<article class="cl-provider-card"><header><strong>${escape(row.name || row.id)}</strong><span class="cl-state">${escape(t(row.state))}</span></header>${row.source_kind ? '<p class="cl-muted">'+escape(t('streaming_kind.'+row.source_kind))+'</p>' : ''}<p class="cl-provider-count">${escape(t('provider_results'))}: <strong>${escape(row.count ?? 0)}</strong></p>${failures.map((failure) => `<small>${escape(t('streaming_provider_failed'))} · ${escape(failure.country)} · ${escape(failure.media_type)}${failure.http_status ? ' · HTTP '+escape(failure.http_status) : ''} · ${escape(failure.error_type)}${failure.reason ? ' · '+escape(t(failure.reason)) : ''}${failure.browser ? ' · Chromium: '+escape(failure.browser.stage)+(failure.browser.http_status ? ' · HTTP '+escape(failure.browser.http_status) : '')+' · '+escape(failure.browser.error_type)+(failure.browser.reason ? ' · '+escape(failure.browser.reason) : '') : ''}</small>`).join('')}</article>`;
    }).join('')}</div>`;
  }
  let seasonalCalendar = [], seasonalCalendarVersion = 0;
  const tributeNames = {fr:'En hommage à …',en:'In tribute to …',de:'In Erinnerung an …',es:'En homenaje a …',it:'In omaggio a …'};
  const itemLibraries = (item) => (item.libraries || [item.library]).map(libraryFor).filter(Boolean);
  function updateName() {
    const memoria = field('model').value === 'memoria';
    field('name').readOnly = true;
    const spotlightNames = {fr:'Sélection du moment 🍿',en:'In the spotlight 🍿',de:'Im Rampenlicht 🍿',es:'En primer plano 🍿',it:'In primo piano 🍿'};
    const countryModel = field('model').value === 'streaming_country';
    const countryName = config.streaming_names[field('language').value][field('country').value];
    field('name').value = field('model').value === 'seasonal' ? config.seasonal_names[field('language').value][field('country').value] : field('model').value === 'recent_releases' ? config.recent_names[field('language').value][field('country').value] : field('model').value === 'streaming_worldwide' ? config.region_names[field('language').value][field('region').value || 'worldwide'] : countryModel ? countryName : memoria ? tributeNames[field('language').value] : field('model').value==='spotlight' ? spotlightNames[field('language').value] : t('model.'+field('model').value);
    if (field('model').value === 'platforms') field('name').value=t('model.platforms')+' · '+(field('country').selectedOptions?.[0]?.textContent || field('country').value);
    if (field('model').value === 'awards') {
      const period=field('award_period').value || 'latest';
      const winners={fr:'Lauréats',en:'Winners',de:'Preisträger',es:'Ganadores',it:'Vincitori'};
      const latest={fr:'Dernière édition',en:'Latest edition',de:'Letzte Ausgabe',es:'Última edición',it:'Ultima edizione'};
      const allYears={fr:'Toutes les années',en:'All years',de:'Alle Jahre',es:'Todos los años',it:'Tutti gli anni'};
      const language=field('language').value;
      field('name').value=config.awards_names[language][field('award').value || 'oscars']+' · '+winners[language]+' · '+(period==='latest' ? latest[language] : period==='all' ? allYears[language] : period);
    }
    if (field('model').value === 'top_country') field('name').value = config.top_country_names[field('language').value][field('country_chart').value || 'top'][field('country').value];
    if (field('model').value === 'hidden_gems') field('name').value = config.hidden_gems_names[field('language').value];
    if (field('model').value === 'family') field('name').value = config.family_names[field('language').value];
    if (field('model').value === 'recently_added') field('name').value = config.recently_added_names[field('language').value];
    if (field('model').value === 'kids') field('name').value = config.kids_names[field('language').value][field('kids_chart').value || 'top'][field('country').value];
    if (field('model').value === 'imdb') {
      const selected = field('imdb_chart').value || 'top';
      const charts = config.imdb_charts[field('language').value];
      field('imdb_chart').replaceChildren(...charts.map((chart) => new Option(chart.label,chart.id)));
      field('imdb_chart').value = selected;
      field('name').value = 'IMDb · '+charts.find((chart) => chart.id === selected).label;
    }
    if (field('model').value === 'tmdb') {
      const selected = field('tmdb_chart').value || 'top_movies';
      const charts = config.tmdb_charts[field('language').value];
      field('tmdb_chart').replaceChildren(...charts.map((chart) => new Option(chart.label,chart.id)));
      field('tmdb_chart').value = selected;
      field('name').value = 'TMDb · '+charts.find((chart) => chart.id === selected).label;
    }
    if (['streaming_country','streaming_worldwide','kids','top_country'].includes(field('model').value) && field('content_language')?.value) field('name').value += ' · '+config.content_languages[field('content_language').value];
  }
  function updatePrerequisites() {
    $('#cl-tmdb-required').hidden = Boolean(sharedSettings.has_tmdb_key);
    $('#cl-editor-key-warning').hidden = Boolean(sharedSettings.has_tmdb_key) || field('model').value === 'seasonal' && field('seasonal_source').value === 'local' || ['recently_added','family','continents'].includes(field('model').value) || !['memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems'].includes(field('model').value);
  }
  function renderSettings(settings) {
    sharedSettings = settings;
    if (!settingsDirty) $('#cl-settings-form [name=suppress_empty]').checked = settings.suppress_empty !== false;
    $('#cl-settings-form input').placeholder = settings.has_tmdb_key ? '••••••••••••' : '';
    updatePrerequisites();
    $('#cl-shared-key-status').textContent = t(settings.has_tmdb_key ? 'tmdb_key_saved' : 'tmdb_key_hint');
    $('#cl-shared-key-conflict').hidden = !settings.legacy_key_conflict;
  }
  function updateEditorLock() {
    const locked = Boolean(editingId && drafts.find((item) => item.id === editingId)?.locked);
    $('#cl-editor-busy').hidden = !locked;
    $('#cl-save').disabled = saveBusy;
  }
  async function stopInstance(id) {
    await api('/api/collections/'+encodeURIComponent(id)+'/stop',{});
    notify(t('stop_requested'),{persistent:true});
    await refresh();
  }
  function updateLimit() {if (field('model').value === 'franchises') {field('all_media').checked = true; field('all_media').disabled = true;} field('limit').disabled = field('all_media').checked; if (!field('all_media').checked && Number(field('limit').value)<1) field('limit').value = '30';}
  function notify(message, {error = false, persistent = false, configure = false, focus = false} = {}) {
    const node = $("#cl-feedback");
    const openDialog = editor.open ? editor : preview.open ? preview : peopleDialog.open ? peopleDialog : null;
    if (openDialog) openDialog.querySelector('.cl-dialog-body').prepend(node);
    else root.insertBefore(node,$('#cl-panel-catalog'));
    $('#cl-feedback-message').textContent = message;
    $('#cl-feedback-resume').hidden = !pendingSave;
    $('#cl-feedback-settings').hidden = !configure;
    node.dataset.kind = error ? 'error' : 'success';
    node.setAttribute('role',error ? 'alert' : 'status');
    node.setAttribute('aria-live',error ? 'assertive' : 'polite');
    node.hidden = false;
    window.clearTimeout(feedbackTimer);
    if (!persistent && !pendingSave) feedbackTimer = window.setTimeout(() => {node.hidden = true;}, 6000);
    if (focus) {node.focus();node.scrollIntoView({block:'center',behavior:'smooth'});}
  }

  try {
    const stored = JSON.parse(window.localStorage.getItem(storageKey) || "[]");
    if (!Array.isArray(stored) || stored.some((item) => !item || typeof item.id !== "string" || !modelFor(item.model) || typeof item.name !== "string" || !["published", "private", "arr"].includes(item.mode))) {
      throw new Error("Invalid collection draft storage");
    }
    localDrafts = stored.map((item) => ({...item,local:true}));
  } catch (error) {
    console.error("[vodum] collection draft storage could not be read", error);
    notify(t("invalid_storage"));
  }

  drafts = [...(config.instances || []), ...localDrafts];

  async function api(path, payload) {
    let response;
    const controller = payload ? null : new AbortController();
    const timeout = controller ? window.setTimeout(() => controller.abort(),15000) : null;
    try {
    try {response = await fetch(path, {method:payload ? "POST" : "GET", credentials:"same-origin", cache:"no-store",
      ...(controller ? {signal:controller.signal} : {}),
      headers:{"Content-Type":"application/json","Accept":"application/json", "X-CSRF-Token":document.querySelector('meta[name="csrf-token"]').content},
      ...(payload ? {body:JSON.stringify(payload)} : {})});}
    catch (cause) {const error = new Error(t('request_failed'));error.transient = cause instanceof TypeError || cause.name === 'AbortError';throw error;}
    if (response.redirected) throw new Error(t('session_expired'));
    let data;
    try {data = await response.json();}
    catch (cause) {const error = new Error(t('request_failed') + ` (HTTP ${response.status})`);error.transient = cause.name === 'AbortError' || cause instanceof TypeError;throw error;}
    if (!response.ok || !data.ok) {
      const code = String(data.error || 'request_failed').replace(/^collections\./,'');
      const error = new Error(labels[code] || t('request_failed') + ` (HTTP ${response.status})`);
      error.code = code;
      error.transient = response.status >= 500;
      error.rejected = response.status === 400 || response.status === 409;
      throw error;
    }
    return data;
    } finally {if (timeout !== null) window.clearTimeout(timeout);}
  }

  let refreshFailures = 0, refreshAfter = 0;
  async function refresh({reportError = true, background = false} = {}) {
    if (refreshBusy || document.hidden) return;
    if (background && Date.now() < refreshAfter) return;
    refreshBusy = true;
    try {
      const data = await api('/api/collections?compact=1');
      drafts = [...data.instances, ...localDrafts];
      runs = data.runs;
      countSnapshots = data.counts || {};
      const previousObjects = new Map(collectionObjects.map((object) => [object.id,object]));
      collectionObjects = (data.objects || []).map((object) => {
        const previous = previousObjects.get(object.id);
        return previous && previous.publication_run_id === object.publication_run_id && previous.publication && !previous.publication.media_compact ? {...object,publication:previous.publication} : object;
      });
      const nextActivity = data.instances.map((item) => item.id+':'+item.state).join('|');
      if (activitySignature !== nextActivity) {
        activitySignature = nextActivity;
        document.dispatchEvent(new Event('vodum:task-activity-changed'));
      }
      renderSettings(data.settings);
      const inventory = data.inventory || {};
      $('#cl-inventory-refresh').disabled = ['running','queued'].includes(inventory.task?.status);
      $('#cl-inventory-status').innerHTML = (inventory.last_run ? `<p class="cl-muted">${escape(t('phase.inventory'))} · ${escape(inventory.last_run.duration_seconds ?? '…')} s</p>` : '')+
        (inventory.task?.next_run ? `<p class="cl-muted">${escape(t('inventory_next'))}: ${escape(new Date(inventory.task.next_run).toLocaleString())}</p>` : '')+
        (inventory.libraries || []).map((row) => `<p class="cl-muted"><strong>${escape(row.server_name)} / ${escape(row.name)}</strong> · ${escape(t(row.state==='ready' ? 'inventory_ready' : row.state==='running' ? 'running' : row.state==='error' ? 'error' : 'inventory_waiting'))} · ${escape(row.media_count ?? 0)} · ${escape(row.duration_seconds ?? '—')} s${row.completed_at ? ' · '+escape(new Date(row.completed_at).toLocaleString()) : ''}${row.last_error ? '<br>'+escape(t(row.last_error.replace(/^collections\./,''))) : ''}</p>`).join('');
      renderRows();
      renderHistory();
      updateEditorLock();
      if (peopleDialog.open && peopleInstance) refreshPeople();
      refreshFailures = 0;refreshAfter = 0;
      return true;
    } catch (error) {
      refreshFailures += 1;
      refreshAfter = Date.now() + Math.min(60000,10000 * 2 ** Math.min(refreshFailures-1,3));
      if (refreshFailures === 1) (error.transient ? console.warn : console.error)('[vodum] collection state refresh failed',error);
      if (reportError && !pendingSave) notify(error.message,{error:true});
      return false;
    } finally {refreshBusy = false;}
  }

  let countSnapshots = {};
  const expandedHistory = new Set();
  const historyLoads = new Set();
  root.addEventListener('toggle', async (event) => {
    const key = event.target.dataset.historyKey;
    if (key) {
      if (event.target.open) expandedHistory.add(key); else expandedHistory.delete(key);
      const summary = event.target.querySelector('summary');
      if (summary) summary.textContent = event.target.open ? t('history_show_less') : t('history_show_more')+' ('+event.target.dataset.moreCount+')';
      if (event.target.open) {
        const objects = collectionObjects.filter((object) => object.group_id+':'+object.person_key===key && object.publication?.media_compact);
        if (objects.length && !historyLoads.has(key)) {
          historyLoads.add(key);
          try {
            await Promise.all(objects.map(async (object) => {
              const data = await api('/api/collections/objects/'+encodeURIComponent(object.id)+'/publication');
              const current = collectionObjects.find((row) => row.id===object.id);
              if (current && current.publication_run_id===data.run_id) current.publication=data.publication;
            }));
            renderHistory();
          } catch (error) {notify(error.message,{error:true});}
          finally {historyLoads.delete(key);}
        }
      }
    }
  }, true);
  function renderHistory() {
    $('#cl-run-count').textContent = runs.length;
    const cards = new Map();
    // Remote objects are the source of truth: previews and attempts never
    // create a history card. A paired movie/TV configuration shares one tribute.
    collectionObjects.forEach((object) => {
      const identity = object.group_id+':'+object.person_key;
      if (!cards.has(identity)) cards.set(identity,{...object, members:[]});
      cards.get(identity).members.push(object);
    });
    const content = [...cards.values()].map((card) => {
      const media = new Map(), libraries = new Set(), diagnostics = [];
      let present = 0, missing = 0, deferredMedia = 0, arrRequests = 0;
      card.members.forEach((object) => {
        libraries.add(object.library_name);
        const history = runs.filter((run) => run.instance_id===object.instance_id && run.kind!=='preview');
        const publication = object.publication || history.flatMap((run) => (run.result?.people || []).filter((person) => person.person_key===object.person_key && person.published===true))[0];
        const rows = publication?.media || (publication?.selected || []).map((title) => ({title,media_type:object.library_name,present:true,arr_status:'not_needed'}));
        if (publication?.media_compact) deferredMedia += Math.max(0,publication.media_total-rows.length);
        arrRequests += Number(publication?.arr_requests ?? rows.filter((row) => row.arr_status==='added').length);
        present += Number(publication?.present ?? rows.filter((row) => row.present===true || row.arr_status==='not_needed').length);
        missing += Number(publication?.missing ?? rows.filter((row) => row.present!==true && row.arr_status!=='not_needed').length);
        rows.forEach((row) => media.set((row.media_type || object.library_name)+':'+(row.tmdb_id || row.library_item_ids?.join(',') || row.title),row));
        const latest = history[0];
        if (latest) {
          const messages = [...new Set([...(latest.result?.errors || []),...(latest.result?.warnings || [])].map((message) => t(message.split(':')[0].replace(/^collections\./,''))))];
          diagnostics.push(`<p class="cl-muted">${escape(object.library_name)} · ${escape(t(latest.state))} · ${escape(new Date(latest.started_at).toLocaleString())}</p>${messages.length ? `<p class="cl-notice">${messages.map(escape).join(' · ')}</p>` : ''}`);
        }
      });
      const rows = [...media.values()];
      const key = card.group_id+':'+card.person_key;
      const expanded = expandedHistory.has(key);
      let retention = '';
      if (card.model === 'memoria') {
        const deadlines = card.members.map((object) => object.expires_at ? Date.parse(object.expires_at) : NaN).filter(Number.isFinite);
        if (deadlines.length) {
          const deadline = Math.min(...deadlines);
          const days = Math.max(0, Math.ceil((deadline - Date.now()) / 86400000));
          const remaining = days === 0 ? t('tribute_expired_pending') : t(days === 1 ? 'tribute_day_remaining' : 'tribute_days_remaining').replace('{days}', String(days));
          retention = `<p class="cl-notice">${escape(remaining)} · ${escape(t('expires_at'))} ${escape(new Date(deadline).toLocaleString())}</p>`;
        }
      }
      const renderMedia = (row) => `<div class="cl-history-media-row"><span>${escape(row.title)}${row.sources?.length ? `<small>${row.sources.map((source) => escape(source)+' #'+escape(row.ranks_by_source?.[source] || '—')).join(' · ')}</small>` : ''}</span><span class="cl-muted">${escape(row.media_type==='movie' ? t('movies') : row.media_type==='tv' ? t('shows') : row.media_type || '')}</span><span class="cl-history-status" data-status="${escape(row.arr_status)}">${escape(t('arr_status.'+row.arr_status))}</span></div>`;
      return `<article class="cl-arr-box cl-history-run" data-configuration-id="${escape(card.group_id)}"><p class="cl-muted">${escape(card.configuration_name)} · ${escape([...libraries].join(' / '))}</p><section class="cl-history-person"><div class="cl-person-heading">${card.model==='memoria' ? portrait(card) : ''}<strong>${escape(card.title)}</strong></div>${retention}<p class="cl-muted">${escape(t('present'))}: ${present} · ${escape(t('missing'))}: ${missing} · ${escape(t('arr_requests'))}: ${arrRequests}</p>${rows.length ? `<div class="cl-history-media">${rows.slice(0,5).map(renderMedia).join('')}${rows.length+deferredMedia>5 ? `<details class="cl-history-more" data-more-count="${rows.length+deferredMedia-5}" data-history-key="${escape(key)}" ${expanded ? 'open' : ''}><summary>${escape(expanded ? t('history_show_less') : t('history_show_more')+' ('+(rows.length+deferredMedia-5)+')')}</summary>${expanded ? rows.slice(5).map(renderMedia).join('') : ''}</details>` : ''}</div>` : `<p class="cl-muted">${escape(t('history_no_media'))}</p>`}</section>${diagnostics.length ? `<details class="cl-history-debug"><summary>${escape(t('history_executions'))}</summary>${diagnostics.join('')}</details>` : ''}</article>`;
    }).join('');
    $('#cl-history-results').innerHTML = content;
    $('#cl-history-empty').hidden = Boolean(content);
  }

  function tab(id) {
    all("[data-tab]").forEach((button) => {
      const selected = button.dataset.tab === id;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    ["catalog", "instances", "history", "settings"].forEach((name) => {$("#cl-panel-" + name).hidden = name !== id;});
  }

  all("[data-tab]").forEach((button, index, tabs) => {
    button.addEventListener("click", () => tab(button.dataset.tab));
    button.addEventListener("keydown", (event) => {
      let target;
      if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") target = (index + tabs.length - 1) % tabs.length;
      if (event.key === "Home") target = 0;
      if (event.key === "End") target = tabs.length - 1;
      if (target !== undefined) {event.preventDefault(); tabs[target].click(); tabs[target].focus();}
    });
  });

  $("#cl-catalog-search").addEventListener("input", (event) => {
    const query = event.target.value.trim().toLocaleLowerCase();
    let visible = 0;
    all("[data-model-card]").forEach((card) => {
      card.hidden = !card.dataset.search.toLocaleLowerCase().includes(query);
      if (!card.hidden) visible++;
    });
    $("#cl-no-models").hidden = visible > 0;
  });

  function examples() {
    return ["memoria", "seasonal", "streaming_country"].map((model, index) => ({
      id: "example-" + model, model, name: t("model." + model), library: "",
      mode: ["published", "private", "arr"][index], frequency: "daily", language: "fr", country: "FR",
      limit: modelFor(model).default_limit, sort: modelFor(model).default_sort, priority: (index + 1) * 10,
      retention: 7, credits: "actors_directors", events: ["halloween"], period: "30",
      arr_enabled: index === 2, arr_server: "", example: true,
    }));
  }

  const sourceNote = (model) => t(model === "hidden_gems" ? "hidden_gems_source" : model === "platforms" ? "platforms_source" : model === "continents" ? "continents_source" : model === "franchises" ? "franchises_source" : model === "top_country" ? "top_country_source" : model === "awards" ? "awards_source" : model === "family" ? "family_source" : model === "tmdb" ? "tmdb_source" : model === "kids" ? "kids_source" : model === "recently_added" ? "recently_added_source" : model === "imdb" ? "imdb_source" : model === "memoria" ? "memoria_source" : model === "seasonal" ? "seasonal_source" : model === "recent_releases" ? "releases_source" : model === "spotlight" ? "spotlight_source" : model === "streaming_country" ? "streaming_source" : model === "streaming_worldwide" ? "worldwide_source" : "source_pending");

  function summary(item) {
    const model = modelFor(item.model), library = libraryFor(item.library);
    const values = [
      [t("target_library"), itemLibraries(item).map((row) => `${row.server_name} · ${row.name}`).join(" / ") || (item.example ? t("example_library") : t("invalid_library"))],
      [t("mode"), t("mode." + (item.mode === "published" && item.visibility && !Object.values(item.visibility).some(Boolean) ? "private" : item.mode))], [t("language"), String(item.language || "").toUpperCase()],
      [t("frequency"), t(item.frequency)], [t("limit"), item.limit === 0 ? t("all_media") : item.limit],

    ];

    if (item.mode === 'published') for (const key of ['home','shared','recommended']) values.push([t('visibility_'+key),(item.visibility?.[key] ?? true) ? t('enabled') : t('disabled')]);
    if (!['recent_releases','recently_added','family','continents'].includes(item.model) && !(item.model === 'seasonal' && item.seasonal_source === 'local')) values.push([t('arr_title'),item.arr_enabled ? t('arr_on') : t('arr_off')]);
    if (item.model === 'platforms') values.push([t('platforms_select'),(item.platforms || []).map((key) => config.platform_options[key] || key).join(' / ')]);
    if (item.frequency === 'custom') values.push([t('cron'),item.schedule]);
    if (['kids','family','top_country'].includes(item.model) && item.required_audio_language) values.push([t('required_audio_language'),config.content_languages[item.required_audio_language] || item.required_audio_language]);
    if (item.model === 'awards') values.push([t('awards_award'),config.awards_options.find((award)=>award.id===item.award)?.label || item.award],[t('awards_period'),item.award_period==='latest' ? t('awards_latest') : item.award_period==='all' ? t('awards_all') : item.award_period]);
    if (item.model === 'hidden_gems') values.push([t('minimum_rating'),item.minimum_rating ?? 7.5],[t('minimum_votes'),item.minimum_votes ?? 200],[t('maximum_popularity'),item.maximum_popularity ?? 10]);
    if (item.model === 'top_country') values.push([t('country_chart'),t(item.country_chart === 'popular' ? 'country_popular' : 'country_top')],[t('minimum_votes'),item.minimum_votes ?? 100]);
    if (item.model === 'kids') values.push([t('kids_chart'),t(item.kids_chart === 'latest' ? 'kids_latest' : 'kids_top')]);
    if (item.model === 'imdb') values.push([t('imdb_chart'),config.imdb_charts[item.language].find((chart) => chart.id === item.imdb_chart)?.label || item.imdb_chart]);
    if (item.model === 'tmdb') values.push([t('tmdb_chart'),config.tmdb_charts[item.language].find((chart) => chart.id === item.tmdb_chart)?.label || item.tmdb_chart]);
    values.push([t('enabled_label'), t(item.enabled ? 'enabled' : 'disabled')]);
    if (["streaming_country","streaming_worldwide","kids","awards","top_country"].includes(item.model) && item.content_language) values.push([t("content_language"), config.content_languages[item.content_language] || item.content_language]);
    if (item.model === "streaming_worldwide") values.push([t("region"), item.region || "worldwide"]);
    if (["streaming_country", "recent_releases", "seasonal", "kids", "top_country", "platforms"].includes(item.model)) values.push([t(item.model === 'top_country' ? 'origin_country' : 'country'), item.country || "—"]);
    if (item.mode !== "arr") values.push([t("sort"), t("sort." + item.sort)]);
    if (item.mode !== "arr") values.push([t("priority"), item.priority]);
    if (item.model === "memoria") values.push([t("retention"), item.retention],[t("max_people"),item.max_people || 4],[t("min_popularity"),item.min_popularity ?? 25]);
    if (item.model === "seasonal") {
      values.push([t("seasonal_selection"),t("seasonal_source."+(item.seasonal_source || "both"))]);
      (item.events || []).forEach((event) => {const row = seasonalCalendar.find((entry) => entry.id === event);values.push([row?.name || t("event."+event),row?.available ? `${row.date} · ${row.start} → ${row.end}` : t("seasonal_event_unavailable")]);});
    }
    if (item.model === "spotlight") values.push([t("spotlight_retention"),item.retention],[t("spotlight_window"),item.release_window_days],[t("spotlight_min_score"),item.min_score],[t("spotlight_audio"),item.audio_language]);
    return `<div class="cl-review-title"><span aria-hidden="true">${escape(model.glyph)}</span><div><strong>${escape(item.name)}</strong><small>${escape(t("model." + item.model))} · ${escape(t(item.local ? "draft" : "configuration"))}</small></div></div><dl class="cl-review-list">${values.map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl><p class="cl-muted">${escape(sourceNote(item.model))}</p>`;
  }

  function renderRows() {
    const rows = [...drafts, ...(examplesVisible ? examples() : [])]
      .sort((a,b) => Number(['running','stopping'].includes(b.state)) - Number(['running','stopping'].includes(a.state)) || Number(a.priority ?? 10) - Number(b.priority ?? 10));
    const activity = $('#cl-collection-activity');
    if (activity) {
      const active = drafts.filter((item) => ['running','stopping'].includes(item.state));
      const queued = drafts.filter((item) => item.state === 'queued');
      activity.hidden = false;
      activity.textContent = [active.length ? t('running')+': '+active.map((item) => item.name).join(', ') : t('none_running'), queued.length ? t('waiting')+': '+queued.length : ''].filter(Boolean).join(' · ');
      const lastRun = runs.find((run) => !['visibility','preview'].includes(run.kind) && run.finished_at);
      if (lastRun) activity.textContent += ' · '+t('last_activity')+': '+lastRun.name+' · '+t(lastRun.state)+' · '+new Date(lastRun.finished_at).toLocaleString()+(lastRun.result?.elapsed_seconds != null ? ' · '+lastRun.result.elapsed_seconds+' s' : '');
    }
    $("#cl-count").textContent = drafts.length;
    $("#cl-tab-count").textContent = drafts.length;
    $("#cl-table-wrap").hidden = rows.length === 0;
    $("#cl-empty").hidden = rows.length > 0;
    $("#cl-example-notice").hidden = !examplesVisible;
    $("#cl-examples").textContent = t(examplesVisible ? "hide_examples" : "show_examples");
    $("#cl-rows").innerHTML = rows.map((item) => {
      const library = libraryFor(item.library);
      const libraryText = itemLibraries(item).map((row) => row.name).join(" / ") || (item.example ? t("example_library") : t("invalid_library"));
      const serverText = [...new Set(itemLibraries(item).map((row) => row.server_name))].join(" / ") || "—";
      const latest = (item.member_ids || [item.id]).map((id) => runs.find((run) => run.instance_id === id && !['preview','visibility'].includes(run.kind))).filter(Boolean);
      const memberIds = item.count_member_ids || item.member_ids || [item.id];
      const snapshots = memberIds.map((id) => countSnapshots[id]).filter(Boolean);
      const partialCounts = snapshots.length < memberIds.length;
      const sumCount = (key) => snapshots.reduce((total,row) => total+Number(row[key] || 0),0);
      const countText = snapshots.length ? (partialCounts ? '≥' : '')+sumCount('present')+' / '+(partialCounts ? '≥' : '')+sumCount('missing') : t('counts_not_measured');
      const countNote = snapshots.length ? partialCounts ? t('counts_partial') : '' : t('counts_run_hint');
      const supportsArr = !['recent_releases','recently_added','family','continents'].includes(item.model) && !(item.model === 'seasonal' && item.seasonal_source === 'local');
      const busy = ['running','queued','stopping'].includes(item.state);
      const canRun = ['memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems'].includes(item.model) && !item.example && !item.local && (item.can_run_manual ?? (!busy && item.enabled));
      const runHint = canRun ? 'run' : ['memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems'].includes(item.model) && !item.enabled ? 'collection_disabled' : busy ? 'busy' : 'engine_unavailable';
      const actions = [["preview", "◉"], ["edit", "✎"], ...(!item.example && !item.local && item.model === "memoria" ? [["people","♙"]] : []), ["duplicate", "⧉"], ["delete", "×"], ...(busy ? [["stop","■"]] : [])];
      const lastExecution = runs.find((run) => (item.running_member_ids || []).includes(run.instance_id) && run.state === 'running') || runs.find((run) => (item.member_ids || [item.id]).includes(run.instance_id));
      const preciseError = item.last_error === 'collections.execution_failed' ? lastExecution?.result?.errors?.find((key) => labels[String(key).replace(/^collections\./,'')]) : null;
      const pendingPublication = latest.flatMap((run) => run.result?.warnings || []).find((key) => ['collections.membership_pending','collections.order_pending'].includes(key));
      const platformNote = item.model === 'platforms' ? latest.some((run) => Number(run.result?.diagnostics?.availability_deferred)>0) ? 'platforms_availability_pending' : latest.some((run) => Number(run.result?.diagnostics?.availability_unknown)>0) ? 'platforms_availability_unknown' : '' : '';
      const originNote = item.model === 'continents' ? latest.some((run) => Number(run.result?.diagnostics?.origin_deferred)>0) ? 'continents_origin_pending' : latest.some((run) => Number(run.result?.diagnostics?.origin_unknown)>0) ? 'continents_origin_unknown' : '' : '';
      const queueGroups = new Map();
      (item.queue_reasons || []).forEach((row) => {
        const key = row.reason+':'+(row.retry_after || '');
        if (!queueGroups.has(key)) queueGroups.set(key,{...row,libraries:[]});
        queueGroups.get(key).libraries.push(row.library_name);
      });
      const queueNote = [...queueGroups.values()].map((row) => [queueGroups.size>1 ? row.libraries.join(', ') : '',t(row.reason.replace(/^collections\./,'')),row.retry_after ? new Date(row.retry_after).toLocaleString() : ''].filter(Boolean).join(' · ')).join(' / ');
      const runNote = item.state === 'queued' ? queueNote : ['running','stopping'].includes(item.state) && lastExecution?.result?.stage ? t('phase.'+(item.model === 'continents' && lastExecution.result.stage === 'selection' ? 'classify_countries' : lastExecution.result.stage)) : item.last_error ? t((preciseError || item.last_error).replace(/^collections\./,'')) : pendingPublication ? t(pendingPublication.replace(/^collections\./,'')) : originNote ? t(originNote) : platformNote ? t(platformNote) : '';
      const shortfallNotes = latest.filter((run) => run.result?.diagnostics?.selection_shortfall).map((run) => {
        const {present,limit} = run.result.diagnostics.selection_shortfall;
        const message = t('limit_shortfall').replace('{present}', String(present)).replace('{limit}', String(limit));
        return latest.length > 1 && run.library_name ? run.library_name+' · '+message : message;
      });
      const presentationNote = item.presentation_state ? t('configuration')+' · '+t(item.presentation_state==='pending' ? 'queued' : item.presentation_state) : '';
      const state = item.example ? 'example' : item.local ? 'draft' : busy ? item.state === 'queued' ? item.queue_state || 'waiting' : item.state : item.last_error ? 'error' : item.enabled ? pendingPublication ? 'publication_pending' : item.state === 'idle' ? 'engine_ready' : lastExecution?.kind==='preview' && item.state==='success' ? 'preview_complete' : lastExecution?.result?.outcome==='waiting' ? 'seasonal_waiting' : lastExecution?.result?.outcome==='empty' ? 'completed_empty' : item.state : 'paused';
      return `<tr><td><strong>${escape(item.name)}</strong><small>${escape(t("model." + item.model))}</small></td><td>${escape(libraryText)}<small>${escape(serverText)}</small></td><td><span class="cl-badge-mode">${escape(t("mode." + (item.mode === "published" && item.visibility && !Object.values(item.visibility).some(Boolean) ? "private" : item.mode)))}</span>${supportsArr ? `<small>${escape(item.arr_enabled ? t("arr_on") : t("arr_off"))}</small>` : ''}</td><td class="cl-priority">${escape(item.priority ?? 10)}</td><td><span class="cl-state">${escape(t(state))}</span>${runNote ? `<small>${escape(runNote)}</small>` : ''}${presentationNote ? `<small>${escape(presentationNote)}</small>` : ''}${shortfallNotes.map((note) => `<small>${escape(note)}</small>`).join('')}${latest.filter((run) => run.result?.diagnostics?.providers?.length).map((run) => `<button type="button" class="cl-provider-trigger" data-provider-sources="${escape(run.instance_id)}" data-provider-configuration="${escape(item.id)}" aria-haspopup="dialog" aria-controls="cl-provider-sources">${escape(t('streaming_providers'))}${latest.length > 1 && run.library_name ? ' · '+escape(run.library_name) : ''} <span>(${run.result.diagnostics.providers.length})</span></button>`).join('')}</td><td>${escape(countText)}${countNote ? `<small>${escape(countNote)}</small>` : ''}<small>${escape(!supportsArr ? t('counts_arr_not_applicable') : !item.arr_enabled && item.mode !== 'arr' ? t('arr_off') : snapshots.length && snapshots.every((row) => row.arr_requests != null) ? 'ARR '+(partialCounts ? '≥' : '')+sumCount('arr_requests') : t('counts_arr_not_measured'))}</small></td><td>${item.last_run ? escape(new Date(item.last_run).toLocaleString()) : '—'}<small>${item.next_run ? escape(new Date(item.next_run).toLocaleString()) : '—'}</small></td><td><div class="cl-row-actions">${actions.filter(([action]) => !item.example || action !== "delete").map(([action, glyph]) => `<button type="button" data-action="${action}" data-id="${escape(item.id)}" ${busy && ['duplicate','delete'].includes(action) || action === 'stop' && item.state === 'stopping' ? 'disabled' : ''} title="${escape(t(action))}" aria-label="${escape(t(action) + ' · ' + item.name)}">${glyph}</button>`).join("")}<button type="button" data-action="run" data-id="${escape(item.id)}" ${canRun ? '' : 'disabled'} title="${escape(t(runHint))}" aria-label="${escape(t(runHint))}">▷</button></div></td></tr>`;
    }).join("");

  }

  function updateLibraries(selected, secondary = field('library_secondary').value) {
    const model = modelFor(field('model').value);
    const chartType = model.id === 'tmdb' ? config.tmdb_charts[field('language').value].find((chart) => chart.id === field('tmdb_chart').value)?.media_type : model.id === 'imdb' ? config.imdb_charts[field('language').value].find((chart) => chart.id === field('imdb_chart').value)?.media_type : null;
    const awardTypes = model.id === 'awards' ? config.awards_options.find((award) => award.id === field('award').value)?.media_types : null;
    const compatible = config.libraries.filter((library) => (String(library.server_status || '').trim().toLowerCase() === 'up' || attachedLibraryIds.has(String(library.id))) && model.media_types.includes(library.media_type) && (!awardTypes || awardTypes.includes(library.media_type)) && (!chartType || library.media_type === chartType));
    field('library').replaceChildren(new Option(t('select_library'),''), ...compatible.map((library) => new Option(`${library.server_name} / ${library.name}${String(library.server_status || '').trim().toLowerCase() === 'up' ? '' : ' · '+t('server_offline')}`,String(library.id))));
    field('library').value = selected || '';
    field('library').disabled = false;
    const first = libraryFor(field('library').value);
    const others = first ? compatible.filter((library) => library.media_type !== first.media_type) : [];
    field('library_secondary').replaceChildren(new Option(t('none'),''),...others.map((library) => new Option(`${library.server_name} / ${library.name}${String(library.server_status || '').trim().toLowerCase() === 'up' ? '' : ' · '+t('server_offline')}`,String(library.id))));
    field('library_secondary').value = secondary || '';
    updateArr();
  }

  function updateArr(selected) {
    const previous = Object.fromEntries(all('[data-arr-library]').map((node) => [node.dataset.arrLibrary,node.value]));
    const saved = selected && typeof selected === 'object' && !(selected instanceof Event) ? selected : {};
    if (typeof selected === 'number' || typeof selected === 'string') saved[field('library').value] = selected;
    const libraries = [field('library').value,field('library_secondary').value].map(libraryFor).filter(Boolean);
    const container = $('#cl-library-arr-status');
    if (['recent_releases','recently_added','family','continents'].includes(field('model').value) || field('model').value === 'seasonal' && field('seasonal_source').value === 'local') {container.replaceChildren();container.hidden = true;return;}
    container.hidden = !libraries.length;
    container.replaceChildren();
    libraries.forEach((library) => {
      const routes = library.arr_routes || [];
      const label = document.createElement('label');
      label.className = 'cl-field';
      label.textContent = `${library.name} · Arr`;
      const select = document.createElement('select');
      select.dataset.arrLibrary = String(library.id);
      select.append(...(routes.length ? routes.map((row) => new Option(row.name,String(row.id))) : [new Option(t('no_arr_link'),'')]));
      const value = saved[library.id] ?? previous[library.id];
      if (routes.some((row) => String(row.id) === String(value))) select.value = String(value);
      select.disabled = !routes.length;
      label.append(select);
      container.append(label);
    });
  }

  function updateModel(reset = false) {
    const model = modelFor(field("model").value);
    if (!model) return;
    $("#cl-library-hint").textContent = t(["seasonal","spotlight"].includes(model.id) ? "movies_library_only" : "library_hint");
    all("[data-for-model]").forEach((node) => {
      const relevant = node.dataset.forModel.split(",").includes(model.id);
      node.hidden = !relevant;
      const fields = node.matches("input,select") ? [node] : [...node.querySelectorAll("input,select")];
      fields.forEach((input) => {input.disabled = !relevant;});
    });
    if (reset && model.id === "hidden_gems") {field("minimum_rating").value=7.5;field("minimum_votes").value=200;field("maximum_popularity").value=10;}
    if (reset && model.id === "top_country") field("minimum_votes").value=100;
    if (reset) {field("name").value = t("model." + model.id); field("limit").value = model.default_limit;}
    field("frequency").disabled = model.daily;
    if (model.daily) field("frequency").value = "daily";
    $("#cl-daily-note").hidden = !model.daily;
    $("#cl-source-note").textContent = sourceNote(model.id);
    $("#cl-country-label").textContent = t(model.id === "top_country" ? "origin_country" : "country");
    $("#cl-country-hint").textContent = t(model.id === "top_country" ? "top_country_hint" : "country_hint");
    const nativeSorts = {hidden_gems:["rank"],platforms:["added","release"],continents:["added","release"],franchises:["release"],top_country:["rank"],awards:["rank","release","popularity"],family:[field("family_chart").value === "latest" ? "release" : "rank"],tmdb:["rank"],kids:["rank"],recently_added:["added"],imdb:["rank"],memoria:["release","popularity","random"], streaming_country:["rank"], streaming_worldwide:["rank"], seasonal:["daily_random","release","popularity"], recent_releases:["release"], spotlight:["availability"]}[model.id];
    const sorts = [...new Set(["rank","added","random",...nativeSorts])];
    const previousSort = field("sort").value;
    field("sort").replaceChildren(...sorts.map((sort) => new Option(t("sort." + sort), sort)));
    field("sort").value = !reset && sorts.includes(previousSort) ? previousSort : model.id === "family" ? sorts[0] : model.default_sort;
    field('priority').disabled = false;
    field('minimum_votes').min=model.id === 'hidden_gems' ? '1' : '0';
    field('minimum_votes').required=model.id === 'hidden_gems';
    field('all_media').disabled = false;
    if (reset) field('all_media').checked = model.default_limit === 0;

    all('[data-streaming-country]').forEach((option) => {
      option.hidden = !['streaming_country','kids','top_country','platforms'].includes(model.id);
      option.disabled = option.hidden;
    });
    if (!['streaming_country','kids','top_country','platforms'].includes(model.id) && field('country').selectedOptions?.[0]?.hasAttribute('data-streaming-country')) field('country').value = 'FR';
    updateLibraries(field("library").value);
    updateMode();
    updateSchedule();
    updateName();
    updateLimit();
    updatePrerequisites();
    updateSeasonalCalendar();
    if (model.id === 'platforms') refreshPlatformChoices();
  }

  async function updateSeasonalCalendar() {
    if (field('model').value !== 'seasonal') return;
    const version = ++seasonalCalendarVersion;
    try {
      const data = await api('/api/collections/seasonal/calendar?country='+encodeURIComponent(field('country').value)+'&language='+encodeURIComponent(field('language').value));
      if (version !== seasonalCalendarVersion || field('model').value !== 'seasonal') return;
      seasonalCalendar = data.events;
      data.events.forEach((row) => {
        const input = form.querySelector('[name="events"][value="'+row.id+'"]');
        if (!input) return;
        input.disabled = !row.available;
        if (!row.available) input.checked = false;
        $('[data-seasonal-title="'+row.id+'"]').textContent = row.name;
        $('[data-seasonal-window="'+row.id+'"]').textContent = row.available ? row.date+' · '+t('seasonal_display_window')+' '+row.start+' → '+row.end : t('seasonal_event_unavailable');
      });
      if (step === 3) $('#cl-review').innerHTML = summary(readDraft());
    } catch (error) {
      if (version !== seasonalCalendarVersion) return;
      all('[data-seasonal-window]').forEach((node) => {node.textContent = t('seasonal_calendar_failed');});
      notify(error.message,{error:true});
    }
  }

  let platformChoicesVersion = 0;
  async function refreshPlatformChoices() {
    if (field('model').value !== 'platforms') return;
    const version = ++platformChoicesVersion;
    const country = field('country').value || 'FR';
    const libraries = [field('library').value, field('library_secondary').value].map(libraryFor).filter(Boolean);
    const types = new Set(libraries.map((library) => library.type === 'shows' ? 'tv' : 'movie'));
    const mediaType = types.size > 1 ? 'both' : [...types][0] || 'movie';
    try {
      const data = await api('/api/collections/platform-options?'+new URLSearchParams({country,media_type:mediaType}));
      if (version !== platformChoicesVersion || field('model').value !== 'platforms') return;
      const available = new Map(data.platforms.map((row) => [row.id,row.available]));
      all('[name="platforms"]').forEach((input) => {
        if (input.dataset.wanted === undefined) input.dataset.wanted = input.checked ? '1' : '0';
        input.disabled = !available.get(input.value);
        input.checked = !input.disabled && input.dataset.wanted === '1';
      });
      $('#cl-platform-status').textContent = t('platforms_country_hint');
    } catch (error) {
      if (version === platformChoicesVersion) $('#cl-platform-status').textContent = error.message;
    }
  }

  function updateSchedule() {
    $('#cl-schedule-field').hidden = field('frequency').value !== 'custom';
    field('schedule').required = field('frequency').value === 'custom';
    const note = $('#cl-schedule-note');
    note.hidden = !['daily','weekly','monthly'].includes(field('frequency').value);
    note.textContent = t(field('frequency').value === 'monthly' ? 'monthly_schedule_hint' : 'default_schedule_hint');
  }

  function updateMode() {
    const spotlight = ['spotlight','recent_releases','recently_added','family','continents'].includes(field('model').value) || field('model').value === 'seasonal' && field('seasonal_source').value === 'local';
    $('#cl-publication-heading').textContent = t(spotlight ? 'publication_only' : 'publication_acquisition');
    $('#cl-publication-step-label').textContent = t(spotlight ? 'publication_only' : 'step_publication');
    const arrMode = form.querySelector('[name=mode][value=arr]');
    arrMode.closest('label').hidden = spotlight; arrMode.disabled = spotlight;
    if (spotlight && arrMode.checked) field('mode').value = 'published';
    $('#cl-acquisition').hidden = spotlight;
    if (spotlight) field('arr_enabled').checked = false;
    const arrOnly = field("mode").value === "arr";
    $("#cl-visibility").hidden = field("mode").value !== "published";
    $("#cl-sort-field").hidden = arrOnly;
    $("#cl-priority-field").hidden = arrOnly;
    if (arrOnly) field("arr_enabled").checked = true;
    field("arr_enabled").disabled = arrOnly;
    $("#cl-arr-settings").hidden = !field("arr_enabled").checked;
    $("#cl-memoria-arr").hidden = field("model").value !== "memoria";
  }

  function readDraft() {
    const model = modelFor(field("model").value);
    return {
      id: editingId || uid(), model: model.id, engine_key: model.engine_key,
      name: field("name").value.trim(), library: field("library").value,
      libraries:[field("library").value, ...(["memoria","streaming_country","streaming_worldwide","recent_releases","recently_added","kids","family","top_country","franchises","continents","platforms","hidden_gems"].includes(model.id) && field("library_secondary").value ? [field("library_secondary").value] : [])],
      platforms:model.id === "platforms" ? all('[name="platforms"]:checked').filter((input) => !input.disabled).map((input) => input.value) : [],
      award:field("award").value || "oscars", award_period:field("award_period").value || "latest",
      family_chart:field("family_chart").value || "top",
      required_audio_language:["family","kids","top_country"].includes(model.id) ? field("required_audio_language").value : "",
      country_chart: field("country_chart").value || "top", minimum_votes:Number(field("minimum_votes").value || (model.id === "hidden_gems" ? 200 : 100)),
      minimum_rating:Number(field("minimum_rating").value), maximum_popularity:Number(field("maximum_popularity").value),
      kids_chart: field("kids_chart").value || "top",
      tmdb_chart: field("tmdb_chart").value || "top_movies",
      imdb_chart: field("imdb_chart").value || "top",
      visibility:Object.fromEntries(["home","shared","recommended"].map((key)=>[key,field("mode").value === "published" && field("visibility_"+key).checked])),
      mode: field("mode").value, language: field("language").value,
      content_language: ["streaming_country","streaming_worldwide","kids","awards","top_country"].includes(model.id) ? field("content_language").value : "",
      region: field("region").value || "worldwide",
      country: ["streaming_country", "recent_releases", "seasonal", "kids", "top_country", "platforms"].includes(model.id) ? field("country").value : null,
      frequency: field("frequency").value, limit: field("all_media").checked ? 0 : Number(field("limit").value),
      sort: field("sort").value, priority: Number(field("priority").value),
      arr_enabled: field("arr_enabled").checked, arr_servers: Object.fromEntries(all("[data-arr-library]").map((node) => [node.dataset.arrLibrary,node.value])),
      retention: model.id === "spotlight" ? Number(field("spotlight_retention").value) : Number(field("retention").value),
      min_score:Number(field("min_score").value),release_window_days:Number(field("release_window_days").value),audio_language:field("audio_language").value,
      credits: model.id === "memoria" ? field("credits").value : null,
      max_people:Number(field("max_people").value), min_popularity:Number(field("min_popularity").value),
      seasonal_source: model.id === "seasonal" ? field("seasonal_source").value : null,
      events: model.id === "seasonal" ? all('[name="events"]:checked').map((input) => input.value) : [],
      period: null,
      state: "draft", updated_at: new Date().toISOString(),
      enabled: ['memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems'].includes(model.id) && field('enabled').checked,
      schedule: field('schedule').value.trim(),
    };
  }

  function showStep(next) {
    step = next;
    all("[data-step]").forEach((node) => {node.hidden = Number(node.dataset.step) !== step;});
    all("[data-step-indicator]").forEach((node) => {
      node.hidden = Number(node.dataset.stepIndicator) < startStep;
      node.querySelector("span").textContent = Number(node.dataset.stepIndicator) - startStep + 1;
      if (Number(node.dataset.stepIndicator) === step) node.setAttribute("aria-current", "step");
      else node.removeAttribute("aria-current");
    });
    $("#cl-back").disabled = step === startStep;
    $("#cl-next").hidden = step === 3;
    $("#cl-save").hidden = step !== 3;
    $("#cl-step-label").textContent = `${t("step")} ${step - startStep + 1} ${t("of")} ${4 - startStep}`;
    if (step === 3) $("#cl-review").innerHTML = summary(readDraft());
    editor.scrollTop = 0;
    if (editor.open) $("[data-step='" + step + "']").querySelector("input:not(:disabled),select:not(:disabled)")?.focus();
  }

  function validStep() {
    if (step === 0) return Boolean(modelFor(field("model").value));
    if (step === 1 && field("model").value === "seasonal") {
      const first = form.querySelector('[name="events"]');
      first.setCustomValidity(all('[name="events"]:checked').length ? "" : t("name_required"));
    }
    const controls = [...$("[data-step='" + step + "']").querySelectorAll("input,select")];
    for (const input of controls) {if (!input.disabled && !input.reportValidity()) return false;}
    if (step === 1 && !field("name").value.trim()) {field("name").focus(); notify(t("name_required")); return false;}
    return true;
  }

  function openEditor(model = "memoria", item = null, duplicate = false, chooseModel = false) {
    form.reset();
    attachedLibraryIds = new Set(item && !duplicate ? (item.libraries || [item.library]).map(String) : []);
    $("#cl-library-arr-status").replaceChildren();
    all('[name="events"]').forEach((input) => input.setCustomValidity(""));
    editingId = item && !duplicate && !item.example && !item.local ? item.id : null;
    duplicateSource = duplicate && item && !item.example && !item.local ? item.id : null;
    duplicateLibrary = duplicate && item ? item.library : null;
    field("model").value = model;
    all('[name="platforms"]').forEach((input) => {input.checked=true;input.dataset.wanted="1";});
    updateModel(true);
    if (item) {
      for (const key of ["name","language","region","country","content_language","imdb_chart","tmdb_chart","kids_chart","family_chart","country_chart","minimum_votes","minimum_rating","maximum_popularity","award","award_period","required_audio_language","frequency","limit","sort","priority","retention","credits","mode","min_score","release_window_days","audio_language","schedule","max_people","min_popularity","seasonal_source"]) {
        if (item[key] !== undefined && item[key] !== null) field(key).value = String(item[key]);
      }
      if (model === 'spotlight') field('spotlight_retention').value = item.retention || 30;
      if (duplicate && model !== 'memoria') field("name").value = item.name + " · " + t("copy");
      field('all_media').checked = Number(item.limit) === 0;
      if (field('all_media').checked) field('limit').value = '30';
      field("arr_enabled").checked = Boolean(item.arr_enabled);
      field('enabled').checked = Boolean(item.enabled) && !duplicate;
      for (const key of ['home','shared','recommended']) field('visibility_'+key).checked = item.visibility?.[key] ?? item.mode === 'published';
      if (model === 'platforms') all('[name="platforms"]').forEach((input) => {input.checked=(item.platforms || Object.keys(config.platform_options)).includes(input.value);input.dataset.wanted=input.checked ? '1' : '0';});
      all('[name="events"]').forEach((input) => {input.checked = (item.events || []).includes(input.value);});
      updateModel();
      updateLibraries(duplicate ? "" : (item.libraries || [item.library])[0],duplicate ? "" : (item.libraries || [])[1]);
      updateArr(duplicate ? {} : (item.arr_servers || item.arr_server));
    }
    updateName(); updateLimit();
    startStep = chooseModel ? 0 : 1;
    $("#cl-editor-title").textContent = chooseModel ? t("new") : t("model." + model);
    showStep(startStep);
    updateEditorLock();
    editor.showModal();
  }

  document.querySelectorAll("[data-create]").forEach((button) => button.addEventListener("click", () => openEditor("memoria", null, false, true)));
  all("[data-configure]").forEach((card) => {
    card.addEventListener("click", () => openEditor(card.dataset.configure));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {event.preventDefault(); openEditor(card.dataset.configure);}
    });
  });
  all('[name="model"]').forEach((input) => input.addEventListener("change", () => updateModel(true)));
  all('[name="mode"]').forEach((input) => input.addEventListener("change", updateMode));
  field("arr_enabled").addEventListener("change", updateMode);
  field('frequency').addEventListener('change',updateSchedule);
  field("award").addEventListener("change",() => {updateName();updateLibraries(field("library").value);});
  field("award_period").addEventListener("change",updateName);
  field("family_chart").addEventListener("change",() => updateModel());
  field("kids_chart").addEventListener("change",updateName);
  field("country_chart").addEventListener("change",updateName);
  field("imdb_chart").addEventListener("change",() => {updateName();updateLibraries(field("library").value);});
  field("tmdb_chart").addEventListener("change",() => {updateName();updateLibraries(field("library").value);});
  field("library").addEventListener("change", () => updateLibraries(field("library").value));
  field("library_secondary").addEventListener("change",updateArr);
  all('[name="platforms"]').forEach((input) => input.addEventListener('change',() => {input.dataset.wanted=input.checked ? '1' : '0';}));
  for (const name of ['country','library','library_secondary']) field(name).addEventListener('change',refreshPlatformChoices);
  field("language").addEventListener("change",() => {updateName();updateSeasonalCalendar();});
  field("content_language").addEventListener("change",updateName);
  field("region").addEventListener("change",updateName);
  field("country").addEventListener("change",() => {updateName();updateSeasonalCalendar();});
  field("name").addEventListener("change",() => {if (field("model").value === "streaming_country") updateName();});
  field("seasonal_source").addEventListener("change",() => {updateMode();updateArr();updatePrerequisites();});
  field("all_media").addEventListener("change",updateLimit);
  all('[name="events"]').forEach((input) => input.addEventListener("change", () => form.querySelector('[name="events"]').setCustomValidity("")));
  $("#cl-next").addEventListener("click", () => {if (validStep()) showStep(Math.min(step + 1, 3));});
  $("#cl-back").addEventListener("click", () => showStep(Math.max(step - 1, startStep)));
  $("[data-close]").addEventListener("click", () => editor.close());
  sourcesDialog.querySelector('[data-close-sources]').addEventListener('click', () => sourcesDialog.close());
  root.addEventListener('click', (event) => {
    const button = event.target.closest('[data-provider-sources]');
    if (!button) return;
    const run = runs.find((row) => String(row.instance_id) === button.dataset.providerSources && !['preview','visibility'].includes(row.kind));
    const item = drafts.find((row) => String(row.id) === button.dataset.providerConfiguration);
    if (!run || !item) return;
    $('#cl-provider-context').textContent = [item.name,run.library_name].filter(Boolean).join(' · ');
    const result = run.result || {};
    const shortfall = result.diagnostics?.selection_shortfall;
    const missing = shortfall?.missing_candidates || [];
    const missingList = missing.length ? `<section><h3>${escape(t('missing_to_fill'))} (${missing.length})</h3><ol>${missing.map(({title,year,arr_status}) => `<li>${escape(title)}${year ? ' ('+escape(year)+')' : ''}${arr_status ? ' · '+escape(t('arr_status.'+arr_status)) : ''}</li>`).join('')}</ol></section>` : '';
    const missingNote = shortfall && !missing.length ? `<p class="cl-muted">${escape(t(Array.isArray(shortfall.missing_candidates) ? 'missing_none_verified' : 'missing_run_again'))}</p>` : '';
    $('#cl-provider-content').innerHTML = streamingDetails(result) + missingList + missingNote;
    if (!sourcesDialog.open) sourcesDialog.showModal();
  });
  $("[data-close-preview]").addEventListener("click", () => preview.close());
  $("#cl-examples").addEventListener("click", () => {examplesVisible = !examplesVisible; renderRows();});
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if ($('#cl-save').disabled) return;
    if (step !== 3) {if (validStep()) showStep(step + 1); return;}
    const draft = readDraft();
    if (!libraryFor(draft.library)) {showStep(1); notify(t("invalid_library")); return;}
    saveBusy = true;
    $('#cl-save').disabled = true;
    $('#cl-save').textContent = t('saving');
    try {
      const path = duplicateSource ? '/api/collections/'+encodeURIComponent(duplicateSource)+'/duplicate' : editingId ? '/api/collections/'+encodeURIComponent(editingId)+'/save' : '/api/collections';
      const data = await api(path,draft);
      pendingSave = null;
      drafts = [...drafts.filter((item) => item.id !== data.instance.id),data.instance];
      renderRows();
      editor.close(); tab('instances');
      const refreshed = await refresh({reportError:false});
      const warnings = (data.warnings || []).map((key) => t(key.replace(/^collections\./,'')));
      if (refreshed === false) warnings.push(t('saved_refresh_pending'));
      notify([t('saved_server'),...warnings].join(' '),{persistent:true,focus:true});
    } catch (error) {
      console.error('[vodum] saving collection failed',error);
      pendingSave = {draft,editingId,duplicateSource};
      editor.close();
      notify(t(error.rejected ? 'save_rejected' : 'save_failed') + ' ' + error.message,{error:true,persistent:true,configure:error.code === 'tmdb_key_required',focus:true});
    }
    finally {saveBusy = false;updateEditorLock();$('#cl-save').textContent = t('save_draft');}
  });
  $('#cl-feedback-dismiss').addEventListener('click',() => {$('#cl-feedback').hidden = true;});
  $('#cl-tmdb-settings').addEventListener('click',() => {tab('settings');$('#cl-settings-form input').focus();});
  $('#cl-feedback-settings').addEventListener('click',() => {tab('settings');$('#cl-settings-form input').focus();});
  $('#cl-feedback-resume').addEventListener('click',() => {
    if (!pendingSave) return;
    const saved = pendingSave;
    $('#cl-feedback').hidden = true;
    openEditor(saved.draft.model,{...saved.draft,local:true});
    editingId = saved.editingId;
    duplicateSource = saved.duplicateSource;
    showStep(3);
    updateEditorLock();
  });
  function confirmCollectionDelete(item) {
    if (deleteDialog.open) return Promise.resolve(false);
    $('#cl-delete-name').textContent = item.name;
    $('#cl-delete-description').textContent = t(item.local ? 'confirm_delete' : 'delete_server_confirm');
    deleteDialog.returnValue = 'cancel';
    return new Promise((resolve) => {
      deleteDialog.addEventListener('close', () => resolve(deleteDialog.returnValue === 'delete'), {once:true});
      deleteDialog.showModal();
      $('#cl-delete-cancel').focus();
    });
  }

  $("#cl-rows").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const item = [...drafts, ...examples()].find((candidate) => candidate.id === button.dataset.id);
    if (!item) return;
    if (button.dataset.action === 'stop') {
      button.disabled = true;
      try {await stopInstance(item.id);} catch (error) {notify(error.message,{error:true});button.disabled=false;}
      return;
    }
    if (button.dataset.action === 'people') {await openPeople(item);return;}
    const backend = !item.example && !item.local;
    if (button.dataset.action === "preview" && (!backend || !['memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems'].includes(item.model))) {$("#cl-preview-content").innerHTML = summary(item); preview.showModal();}
    if (button.dataset.action === "edit") openEditor(item.model, item);
    if (button.dataset.action === "duplicate") openEditor(item.model, item, true);
    let kind;
    if (button.dataset.action === 'run') kind = 'sync';
    if (button.dataset.action === 'preview' && backend && ['memoria','spotlight','streaming_country','streaming_worldwide','recent_releases','seasonal','imdb','recently_added','kids','tmdb','family','awards','top_country','franchises','continents','platforms','hidden_gems'].includes(item.model)) kind = 'preview';
    if (button.dataset.action === 'delete' && !item.example) {
      if (!await confirmCollectionDelete(item)) return;
      if (backend) kind = 'delete';
      else if (item.local) {
        localDrafts = localDrafts.filter((draft) => draft.id !== item.id);
        window.localStorage.setItem(storageKey,JSON.stringify(localDrafts));
        await refresh();
      }
    }
    if (kind) {
      button.disabled = true;
      try {await api('/api/collections/'+encodeURIComponent(item.id)+'/run',{kind});notify(t('run_queued'));if (kind === 'preview') tab('history');await refresh();}
      catch (error) {console.error('[vodum] queue collection failed',error);notify(error.message,{error:true,persistent:true});button.disabled = false;}
    }
  });
  $('#cl-editor-stop').addEventListener('click',async () => {
    if (!editingId) return;
    $('#cl-editor-stop').disabled = true;
    try {await stopInstance(editingId);} catch (error) {notify(error.message,{error:true});}
    finally {$('#cl-editor-stop').disabled = false;}
  });
  function peopleMessage(message) {
    $('#cl-people-message').textContent = message;
    $('#cl-people-message').hidden = !message;
  }
  function renderPeople(data) {
    peopleEditable = data.editable;
    $('#cl-people-busy').hidden = data.editable;
    $('#cl-people-list').innerHTML = `<p class="cl-muted">${escape(t('people_limit'))}: ${escape(data.max_people)} · ${escape(t('min_popularity'))}: ${escape(data.min_popularity)}</p>` + (data.people.length ? data.people.map((person) => `<article class="cl-person-row">${portrait(person)}<div class="cl-person-info"><div class="cl-person-title"><strong>${escape(person.name)}</strong><span class="cl-person-score">${escape(t('popularity_score'))}: ${escape(person.popularity_score ?? t('score_unknown'))}</span></div><small>${escape(t(person.manual ? 'person_manual' : 'person_auto'))} · ${escape(t('person_state.'+person.status))} · TMDb ${escape(person.tmdb_id)}${person.death_date ? ' · '+escape(person.death_date) : ''}${person.expires_at ? ' · '+escape(t('expires_at'))+' '+escape(new Date(person.expires_at).toLocaleDateString()) : ''}</small></div><button type="button" class="cl-button ${!person.manual && person.status!=='published' ? 'cl-button-primary' : ''}" data-person-action="${person.status==='published' ? 'exclude' : 'add'}" data-person-id="${person.tmdb_id}" ${data.editable ? '' : 'disabled'}>${escape(t(person.status==='published' ? 'exclude_person' : 'validate_person'))}</button></article>`).join('') : `<p class="cl-empty">${escape(t('people_empty'))}</p>`);
    all('#cl-people-results button[data-person-action]').forEach((button) => {button.disabled = !data.editable;});
  }
  async function refreshPeople() {
    const id = peopleInstance, version = peopleVersion;
    if (!id) return;
    try {
      const data = await api('/api/collections/'+encodeURIComponent(id)+'/people');
      if (id === peopleInstance && version === peopleVersion) renderPeople(data);
    } catch (error) {if (id === peopleInstance) peopleMessage(error.message);}
  }
  async function openPeople(item) {
    peopleInstance = item.id; peopleVersion++;
    peopleMessage('');
    $('#cl-people-results').replaceChildren();
    $('#cl-person-search').reset();
    $('#cl-people-list').textContent = t('searching');
    peopleDialog.showModal();
    await refreshPeople();
  }
  $('#cl-people-close').addEventListener('click',() => peopleDialog.close());
  peopleDialog.addEventListener('close',() => {peopleInstance = null;peopleVersion++;});
  $('#cl-person-search').addEventListener('submit',async (event) => {
    event.preventDefault();
    const id = peopleInstance, version = ++peopleVersion;
    const query = event.currentTarget.elements.namedItem('query').value.trim();
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;peopleMessage(t('searching'));
    try {
      const data = await api('/api/collections/'+encodeURIComponent(id)+'/people/search',{query});
      if (id !== peopleInstance || version !== peopleVersion) return;
      peopleMessage('');
      $('#cl-people-results').innerHTML = data.people.length ? data.people.map((person) => `<article class="cl-person-row">${portrait(person)}<div class="cl-person-info"><strong>${escape(person.name)}</strong><small>TMDb ${escape(person.tmdb_id)} · ${escape(person.known_for || person.department)}</small></div><button type="button" class="cl-button" data-person-action="add" data-person-id="${person.tmdb_id}" ${peopleEditable ? '' : 'disabled'}>${escape(t('add_person'))}</button></article>`).join('') : `<p class="cl-muted">${escape(t('no_results'))}</p>`;
    } catch (error) {if (id === peopleInstance) peopleMessage(error.message);}
    finally {button.disabled = false;}
  });
  peopleDialog.addEventListener('click',async (event) => {
    const button = event.target.closest('[data-person-action]');
    if (!button || !peopleInstance) return;
    const id = peopleInstance;button.disabled = true;
    try {
      const data = await api('/api/collections/'+encodeURIComponent(id)+'/people',{action:button.dataset.personAction,tmdb_id:Number(button.dataset.personId)});
      if (id !== peopleInstance) return;
      renderPeople(data);
      peopleMessage([t('people_changed'),...(data.warnings || []).map((key) => t(key.replace(/^collections\./,'')))].join(' '));
      await refresh();
    } catch (error) {if (id === peopleInstance) peopleMessage(error.message);}
    finally {if (button.isConnected) button.disabled = !peopleEditable;}
  });
  $('#cl-inventory-refresh').addEventListener('click',async () => {
    try {await api('/api/collections/inventory/refresh',{});notify(t('run_queued'));await refresh();}
    catch(error) {notify(error.message,{error:true});}
  });
  $('#cl-settings-form').addEventListener('change',() => {settingsDirty = true;});
  $('#cl-settings-form').addEventListener('submit',async (event) => {
    event.preventDefault();
    const input = event.currentTarget.elements.namedItem('shared_tmdb_api_key');
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    try {
      const data = await api('/api/collections/settings',{tmdb_api_key:input.value.trim(),suppress_empty:event.currentTarget.elements.namedItem('suppress_empty').checked});
      settingsDirty = false; input.value = ''; renderSettings(data.settings); notify(t('settings_saved'));
    } catch (error) {console.error('[vodum] shared collection settings failed',error);notify(error.message,{error:true,persistent:true});}
    finally {button.disabled = false;}
  });
  renderSettings(config.settings);
  renderRows();
  refresh();
  window.setInterval(() => refresh({reportError:false,background:true}),2000);
  document.addEventListener('visibilitychange',() => {if (!document.hidden) refresh();});
})();
