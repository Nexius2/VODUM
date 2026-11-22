(() => {
  'use strict';
  const root = document.getElementById('collections-workspace');
  const panel = document.getElementById('cl-panel-lists');
  if (!root || !panel) return;
  const labels = JSON.parse(document.getElementById('cl-lists-labels').textContent);
  const config = JSON.parse(document.getElementById('cl-config').textContent);
  const t = (key) => labels[key] || key;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const nav = document.getElementById('cl-lists-nav');
  const detail = document.getElementById('cl-list-detail');
  const message = document.getElementById('cl-lists-message');
  let selected = null, current = null, catalog = [], generation = 0, busy = false, searchVersion = 0;
  const endpoint = (key = selected) => '/api/collections/lists/' + encodeURIComponent(key);
  function feedback(text) {message.textContent = text; message.hidden = !text;}
  async function api(path, payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);
    try {
      const response = await fetch(path, {method:payload ? 'POST':'GET', credentials:'same-origin', cache:'no-store', signal:controller.signal,
        headers:{'Content-Type':'application/json','Accept':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},
        ...(payload ? {body:JSON.stringify(payload)} : {})});
      if (response.redirected) throw new Error(t('session_expired'));
      const data = await response.json();
      if (!response.ok || !data.ok) {const code=String(data.error || 'request_failed').replace(/^collections\./,'');const error=new Error(t(code));error.code=code;throw error;}
      return data;
    } catch (error) {
      if (error.name === 'AbortError' || error instanceof TypeError) throw new Error(t('request_failed'));
      throw error;
    } finally {clearTimeout(timeout);}
  }
  function origin(row) {return `<span class="cl-list-origin">${esc(t(row.is_vodum ? 'lists_builtin':'lists_custom'))}</span>`;}
  function drawNav() {
    const query = document.getElementById('cl-lists-search').value.trim().toLocaleLowerCase();
    const visible = catalog.filter((row) => row.name.toLocaleLowerCase().includes(query));
    document.getElementById('cl-lists-total').textContent = catalog.length;
    nav.innerHTML = visible.length ? visible.map((row) => `<button type="button" data-list="${esc(row.id)}" aria-current="${row.id===selected ? 'true':'false'}"><span class="cl-list-nav-text"><strong>${esc(row.name)}</strong>${row.enabled ? '' : `<small>${esc(t('lists_disabled'))}</small>`}</span><span class="cl-list-nav-count" aria-label="${esc(row.active+'/'+row.total+' '+t('lists_count'))}">${row.active}<span>/${row.total}</span></span></button>`).join('') : `<p class="cl-list-nav-empty">${esc(t('lists_no_results'))}</p>`;

  }
  function identities(item) {return {provider:item.provider, media_type:item.media_type, external_id:item.external_id};}
  function itemKey(item) {return [item.provider,item.media_type,item.external_id].join(':');}
  function poster(row) {
    const path = row.poster_path;
    const valid = typeof path === 'string' && /^(?:\/[A-Za-z0-9_-]+|imdb:\/images\/M\/[A-Za-z0-9_@.,-]+)\.(jpg|png|webp)$/.test(path);
    return `<span class="cl-list-poster" aria-hidden="true"><svg viewBox="0 0 24 32" fill="none" stroke="currentColor"><rect x="3" y="2" width="18" height="28" rx="2"/><path d="m6 24 5-7 4 4 3-4"/><circle cx="9" cy="10" r="2"/></svg>${valid ? `<img src="/api/collections/portrait?path=${encodeURIComponent(path)}" data-list-poster="${esc(path)}" alt="" loading="lazy" decoding="async">` : ''}</span>`;
  }
  function mediaIssue(row) {
    if (row.metadata_state==='not_found') return t('lists_unmatched').replace('{id}',row.provider.toUpperCase()+' '+row.external_id).replace('{type}',t(row.media_type==='movie' ? 'movies':'shows'));
    if (row.resolve_error) return row.provider.toUpperCase()+' '+row.external_id+' · '+row.resolve_error;
    return '';
  }
  function renderItems() {
    if (!current) return;
    const term = (detail.querySelector('[name="filter"]')?.value || '').trim().toLocaleLowerCase();
    const filtered = current.items.filter((row) => [row.title,row.external_id,row.year].join(' ').toLocaleLowerCase().includes(term));
    detail.querySelector('#cl-list-items').innerHTML = filtered.length ? filtered.map((row) => {
      const issue=mediaIssue(row);
      const title=row.title || row.provider.toUpperCase()+' '+row.external_id;
      return `<tr data-item="${esc(itemKey(row))}" class="${row.enabled ? '' : 'cl-list-item-disabled'}"><td><div class="cl-list-media-cell">${poster(row)}<div class="cl-list-media-title"><strong>${esc(title)}</strong><small>${esc(t(row.media_type==='movie' ? 'movies':'shows'))} · ${row.year ? esc(row.year)+' · ' : ''}${esc(row.provider.toUpperCase())} ${esc(row.external_id)}</small>${issue ? `<p class="cl-list-media-issue">${esc(issue)} <button type="button" class="cl-list-retry" data-item-retry>${esc(t('lists_retry'))}</button></p>` : !row.title ? `<small>${esc(t('lists_metadata_pending'))}</small>` : ''}</div></div></td><td class="cl-list-type">${esc(t(row.media_type==='movie' ? 'movies':'shows'))}</td><td class="cl-list-origin-cell">${origin(row)}</td><td class="cl-list-enabled-cell"><input class="cl-list-switch" type="checkbox" role="switch" data-item-toggle aria-label="${esc(t('lists_enabled')+' · '+title)}" ${row.enabled ? 'checked':''}></td><td class="cl-list-delete-cell">${row.is_vodum ? '' : `<button type="button" class="cl-list-trash" data-item-delete aria-label="${esc(t('lists_delete')+' · '+title)}" title="${esc(t('lists_delete'))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button>`}</td></tr>`;
    }).join('') : `<tr><td colspan="5" class="cl-muted">${esc(t('lists_empty'))}</td></tr>`;
  }
  let linkTargets=[],linkPage=0;
  function renderLinkTargets() {
    const term=(detail.querySelector('#cl-list-links-search').value || '').trim().toLocaleLowerCase();
    const rows=linkTargets.filter((row) => [row.name,...row.libraries.map((lib) => lib.server_name+' '+lib.library_name)].join(' ').toLocaleLowerCase().includes(term));
    const pages=Math.max(1,Math.ceil(rows.length/8));linkPage=Math.max(0,Math.min(linkPage,pages-1));
    detail.querySelector('#cl-list-links-targets').innerHTML=rows.slice(linkPage*8,linkPage*8+8).map((row) => `<label class="cl-list-link-option"><input type="checkbox" data-list-link="${esc(row.id)}" ${row.linked ? 'checked':''} ${row.busy ? 'disabled':''}><span><strong>${esc(row.name)}</strong><small>${esc(row.libraries.map((lib) => lib.server_name+' / '+lib.library_name).join(' · '))}${row.busy ? ' · '+esc(t('busy')):''}</small></span></label>`).join('') || `<p class="cl-muted">${esc(t('lists_no_results'))}</p>`;
    detail.querySelector('#cl-links-prev').disabled=linkPage===0;
    detail.querySelector('#cl-links-next').disabled=linkPage===pages-1;
    detail.querySelector('#cl-links-count').textContent=rows.length ? `${linkPage*8+1}–${Math.min(rows.length,linkPage*8+8)} / ${rows.length}` : '0 / 0';
  }
  function usageLibraries(use) {
    return (use.libraries || [use]).map((library) => `<span>${esc(library.server_name)} / ${esc(library.library_name)}</span>`).join('');
  }
  function drawUsages(row) {
    const heading=`<h4>${esc(t('lists_uses'))}</h4><details id="cl-list-links" class="cl-list-link-manager"><summary>${esc(t('lists_manage_links'))}</summary><p class="cl-muted">${esc(t('lists_links_hint'))}</p><label class="cl-field">${esc(t('lists_search_collections'))}<input id="cl-list-links-search" type="search"></label><div id="cl-list-links-targets"></div><div class="cl-media-list-pagination"><button type="button" class="cl-button" id="cl-links-prev" aria-label="${esc(t('media_list_previous'))}">←</button><span id="cl-links-count" class="cl-muted" role="status"></span><button type="button" class="cl-button" id="cl-links-next" aria-label="${esc(t('media_list_next'))}">→</button></div></details>`;
    const link=(use) => `<button type="button" class="cl-list-usage" data-usage="${esc(use.id)}">${esc(use.name)}</button>`;
    if (!row.usages.length) return heading+`<p class="cl-muted">${esc(t('lists_unused'))}</p>`;
    if (row.usages.length===1) {
      const use=row.usages[0];
      return heading+`<div class="cl-list-single-usage">${link(use)}<div class="cl-list-library-names">${usageLibraries(use)}</div><span class="cl-list-use-state">${esc(t(use.enabled ? 'enabled':'disabled'))}</span></div>`;
    }
    return heading+`<div class="cl-list-table-scroll"><table class="cl-list-table cl-list-usage-table"><thead><tr><th>${esc(t('lists_collection'))}</th><th>${esc(t('lists_libraries'))}</th><th>${esc(t('lists_status'))}</th></tr></thead><tbody>${row.usages.map((use) => `<tr><td>${link(use)}</td><td><div class="cl-list-library-names">${usageLibraries(use)}</div></td><td>${esc(t(use.enabled ? 'enabled':'disabled'))}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function drawDetail() {
    const row = current;
    detail.innerHTML = `<section class="cl-list-usages cl-list-card">${drawUsages(row)}</section>
      <section class="cl-list-content-card cl-list-card"><header class="cl-list-content-heading"><div><h3>${esc(row.name)}</h3><small class="cl-muted">${esc(t(row.is_vodum ? 'lists_builtin':'lists_custom'))} · ${esc(t('lists_contents'))} · ${row.items.length}</small></div><div class="cl-list-header-actions"><button type="button" class="cl-button" id="cl-list-resolve">${esc(t('lists_resolve'))}</button>${row.is_vodum ? '' : `<button type="button" class="cl-list-trash" data-list-delete aria-label="${esc(t('lists_delete_list')+' · '+row.name)}" title="${esc(t(row.usages.length ? 'lists_in_use':'lists_delete_list'))}" ${row.usages.length ? 'disabled':''}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/></svg></button>`}</div></header>
      <details class="cl-list-add"><summary>${esc(t('lists_add_media'))}</summary><p class="cl-muted">${esc(t('lists_add_hint'))}</p><form id="cl-list-search"><label class="cl-field">${esc(t('lists_query'))}<input name="query" type="search" required minlength="2" maxlength="200"></label><button class="cl-button cl-button-primary" type="submit">${esc(t('lists_find'))}</button></form><div id="cl-list-search-results" aria-live="polite"></div></details>
      <div class="cl-list-filter-bar"><label class="cl-field">${esc(t('lists_search_content'))}<input name="filter" type="search" placeholder="${esc(t('lists_filter_hint'))}"></label><span id="cl-list-metadata-progress" class="cl-muted" role="status" aria-live="polite"></span></div>
      <div class="cl-list-table-scroll"><table class="cl-list-table cl-list-media-table"><thead><tr><th>${esc(t('lists_media'))}</th><th class="cl-list-type">${esc(t('lists_type'))}</th><th class="cl-list-origin-cell">${esc(t('lists_origin'))}</th><th class="cl-list-enabled-cell">${esc(t('lists_enabled'))}</th><th class="cl-list-delete-cell"><span class="sr-only">${esc(t('lists_delete'))}</span></th></tr></thead><tbody id="cl-list-items"></tbody></table></div><p class="cl-list-sync-note cl-muted">${esc(t('lists_next_sync'))}</p></section>`;
    renderItems();
    linkTargets=[];linkPage=0;
    const linkPanel=detail.querySelector('#cl-list-links');
    linkPanel.addEventListener('toggle',async () => {
      if (!linkPanel.open) return;
      const token=generation;
      try {
        const data=await api(endpoint()+'/links');
        if (token!==generation) return;
        linkTargets=data.targets;renderLinkTargets();
      } catch (error) {if(token===generation) feedback(error.message);}
    });
    detail.querySelector('#cl-list-links-search').addEventListener('input',() => {linkPage=0;renderLinkTargets();});
    detail.querySelector('#cl-links-prev').addEventListener('click',() => {linkPage--;renderLinkTargets();});
    detail.querySelector('#cl-links-next').addEventListener('click',() => {linkPage++;renderLinkTargets();});
    detail.querySelector('[name="filter"]').addEventListener('input',renderItems);
    detail.querySelector('#cl-list-search').addEventListener('submit',findMedia);
    detail.querySelector('#cl-list-resolve').addEventListener('click',() => resolveTitles(generation,null,true));
  }
  async function refreshCatalog() {
    catalog=(await api('/api/collections/lists')).lists;
    drawNav();
  }
  async function openList(key) {
    const token=++generation; ++searchVersion; selected=key;current=null; drawNav();
    detail.innerHTML=`<p class="cl-muted">${esc(t('lists_loading'))}</p>`;
    try {
      const data=await api(endpoint(key)); if (token!==generation) return;
      current=data.list;drawDetail();
      if (config.settings?.has_tmdb_key) resolveTitles(token);
    } catch (error) {if (token===generation) feedback(error.message);}
  }
  async function mutate(operation, deleted=false) {
    if (busy) return; busy=true;feedback('');
    panel.setAttribute('aria-busy','true');
    try {
      const data=await operation();
      if (data.definitions) root.dispatchEvent(new CustomEvent('vodum:lists-updated',{detail:data.definitions}));
      if (deleted) document.getElementById('cl-lists-search').value='';
      await refreshCatalog();
      feedback(t(deleted ? 'deleted':'lists_saved'));
      const key=deleted ? catalog[0]?.id : selected;
      if (key) await openList(key); else {++generation;current=null;selected=null;detail.innerHTML=`<p>${esc(t('lists_choose'))}</p>`;}
    } catch (error) {feedback(error.message); if (current) renderItems();}
    finally {busy=false;panel.removeAttribute('aria-busy');}
  }
  let resolvingToken=null;
  async function resolveTitles(token, only=null, retry=false) {
    if (!current || resolvingToken===token) return;
    const row=current, key=selected;
    const queue=only || row.items.filter((item) => (item.metadata_state!=='resolved' || !item.poster_path) && (retry || (item.metadata_state!=='not_found' && item.metadata_state!=='partial') || (item.metadata_state==='not_found' && item.provider==='imdb' && item.metadata_error!=='collections.lists_metadata_missing')));
    const total=queue.length;
    const button=detail.querySelector('#cl-list-resolve');
    if (!queue.length) {if (button) button.hidden=!row.items.some((item) => item.metadata_state!=='resolved' || !item.poster_path);return;}
    resolvingToken=token;
    if (button) {button.disabled=true;button.textContent=t('lists_loading');}
    let completed=0, failures=0, stopped=false;
    const progress=detail.querySelector('#cl-list-metadata-progress');
    const updateProgress=() => {if (token===generation && progress) progress.textContent=t('lists_metadata_progress').replace('{done}',completed).replace('{total}',total);};
    updateProgress();
    async function worker() {
      while (queue.length && token===generation && !panel.hidden && !stopped) {
        const item=queue.shift();
        try {
          const data=await api(endpoint(key)+'/resolve',{...identities(item),retry});
          if (token!==generation) return;
          Object.assign(item,data.media);delete item.resolve_error;failures=0;
        } catch (error) {
          if (token!==generation) return;
          item.resolve_error=error.message;
          if (++failures>=3 || error.code==='tmdb_key_required' || error.code==='session_expired') stopped=true;
        }
        completed++;updateProgress();renderItems();
      }
    }
    try {await Promise.all([worker(),worker()]);}
    finally {
      if (resolvingToken===token) resolvingToken=null;
      if (token===generation) {
        if (progress) progress.textContent='';
        if (button) {button.disabled=false;button.textContent=t('lists_resolve');button.hidden=!row.items.some((item) => item.metadata_state!=='resolved' || !item.poster_path);}
      }
    }
  }
  detail.addEventListener('error',(event) => {
    const image=event.target;
    if (!(image instanceof HTMLImageElement) || !image.dataset.listPoster) return;
    const attempt=Number(image.dataset.retry || 0);
    if (attempt<2) {
      image.dataset.retry=String(attempt+1);
      setTimeout(() => {if (image.isConnected) image.src='/api/collections/portrait?'+new URLSearchParams({path:image.dataset.listPoster,retry:String(attempt+1)});},(attempt+1)*1200);
    } else image.remove();
  },true);
  function confirmItemDelete(row, wholeList=false) {
    const dialog=document.getElementById('cl-list-delete-confirm');
    if (dialog.open) return Promise.resolve(false);
    document.getElementById('cl-list-delete-name').textContent=wholeList ? row.name : row.title || row.external_id;
    document.getElementById('cl-list-delete-title').textContent=t(wholeList ? 'lists_delete_list':'lists_delete');
    document.getElementById('cl-list-delete-description').textContent=t(wholeList ? 'lists_delete_list_confirm':'lists_delete_confirm');
    dialog.returnValue='cancel';
    return new Promise((resolve) => {
      dialog.addEventListener('close',() => resolve(dialog.returnValue==='delete'),{once:true});
      dialog.showModal();
      dialog.querySelector('[value="cancel"]').focus();
    });
  }
  let searchResults=[];
  async function findMedia(event) {
    event.preventDefault(); const form=event.currentTarget,token=generation,version=++searchVersion;
    const target=detail.querySelector('#cl-list-search-results');
    target.textContent=t('lists_loading');
    try {
      const data=await api('/api/collections/lists/search?'+new URLSearchParams({q:form.elements.query.value}));
      if (token!==generation || version!==searchVersion) return;
      searchResults=data.results;
      target.innerHTML=searchResults.length ? searchResults.map((row,index) => `<div class="cl-list-result"><span>${poster(row)}${esc(row.title)} ${esc(row.year)} <small>${esc(t(row.media_type==='movie' ? 'movies':'shows'))}</small></span><button type="button" class="cl-button" data-add-result="${index}">${esc(t('lists_add'))}</button></div>`).join('') : `<p>${esc(t('lists_empty'))}</p>`;
    } catch (error) {if (token===generation && version===searchVersion) target.textContent=form.elements.query.value+' : '+error.message;}
  }
  document.getElementById('cl-lists-search').addEventListener('input',drawNav);
  nav.addEventListener('click',(event) => {const button=event.target.closest('[data-list]');if (button && !busy) {feedback('');openList(button.dataset.list);}});
  detail.addEventListener('click',async (event) => {
    const removeList=event.target.closest('[data-list-delete]');
    if (removeList) {
      const row=current,key=selected,token=generation;
      if (!row || row.is_vodum || busy || removeList.disabled) return;
      if (row.usages.length) {feedback(t('lists_in_use'));return;}
      if (await confirmItemDelete(row,true) && token===generation && key===selected && !busy)
        mutate(() => api(endpoint(key),{action:'delete'}),true);
      return;
    }

    const retry=event.target.closest('[data-item-retry]');
    if (retry) {const row=current.items.find((item) => itemKey(item)===retry.closest('[data-item]').dataset.item);if (row) resolveTitles(generation,[row],true);}
    const usage=event.target.closest('[data-usage]');
    if (usage) root.dispatchEvent(new CustomEvent('vodum:list-usage',{detail:usage.dataset.usage}));
    const add=event.target.closest('[data-add-result]');
    if (add) {const row=searchResults[Number(add.dataset.addResult)];if (row) mutate(async () => {try {return await api(endpoint()+'/items',{action:'add',...identities(row)});} catch (error) {error.message=row.title+' · '+row.provider.toUpperCase()+' '+row.external_id+' : '+error.message;throw error;}});}
    const remove=event.target.closest('[data-item-delete]');
    if (remove && !busy) {
      const row=current.items.find((row) => itemKey(row)===remove.closest('[data-item]').dataset.item);
      const key=selected, token=generation;
      if (row && await confirmItemDelete(row) && token===generation && key===selected && !busy)
        mutate(() => api(endpoint(key)+'/items',{action:'delete',...identities(row)}));
    }
  });
  detail.addEventListener('change',async (event) => {
    if (!event.target.matches('[data-list-link]')) return;
    const input=event.target,token=generation,key=selected;
    if (busy) {input.checked=!input.checked;return;}
    busy=true;input.disabled=true;feedback('');
    try {
      const data=await api(endpoint(key)+'/links',{collection_id:input.dataset.listLink,linked:input.checked});
      root.dispatchEvent(new CustomEvent('vodum:list-links-updated',{detail:data}));
      await refreshCatalog();
      if (token!==generation) return;
      const detailData=await api(endpoint(key));
      if (token!==generation) return;
      const search=detail.querySelector('#cl-list-links-search').value,page=linkPage;
      current=detailData.list;drawDetail();
      detail.querySelector('#cl-list-links-search').value=search;linkPage=page;
      detail.querySelector('#cl-list-links').open=true;
      feedback(t('lists_saved'));
    } catch(error) {if(token===generation) {input.checked=!input.checked;feedback(error.message);}}
    finally {busy=false;if(input.isConnected) input.disabled=false;}
  });
  detail.addEventListener('change',(event) => {
    if (!event.target.matches('[data-item-toggle]')) return;
    const row=current.items.find((row) => itemKey(row)===event.target.closest('[data-item]').dataset.item);
    const enabled=event.target.checked;
    if (row) mutate(() => api(endpoint()+'/items',{action:'toggle',enabled,...identities(row)}));
  });
  document.getElementById('cl-list-create').addEventListener('submit',(event) => {
    event.preventDefault();const form=event.currentTarget;
    mutate(async () => {const data=await api('/api/collections/lists',{name:form.elements.name.value});selected=data.id;form.reset();document.getElementById('cl-lists-search').value='';form.closest('details').open=false;return data;});
  });
  document.getElementById('cl-tab-lists').addEventListener('click',async () => {
    try {await refreshCatalog();if (selected && catalog.some((row) => row.id===selected)) await openList(selected);else if (catalog.length) await openList(catalog[0].id);}
    catch (error) {feedback(error.message);}
  });
})();
