(function () {
  const feedback = document.getElementById('request-feedback');
  if (!feedback) return;
  const messages = JSON.parse(feedback.dataset.messages);
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
    toast.dataset.tone = ['portal_requests_present', 'portal_requests_added'].includes(result) ? 'success' : (result === 'portal_requests_pending' ? 'info' : 'error');
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
      const button = form.querySelector('button');
      const label = button.textContent;
      const progress = form.querySelector('[data-request-progress]');
      if (!startProgress(form, progress)) return;
      close();
      button.disabled = true; button.textContent = form.dataset.working;
      form.setAttribute('aria-busy', 'true');
      try {
        const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: {Accept: 'application/json'}});
        if (response.redirected) throw new Error('Session unavailable');
        const data = await response.json();
        stopProgress(form);
        show(data.result || 'portal_requests_unavailable');
      } catch (_) {
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
