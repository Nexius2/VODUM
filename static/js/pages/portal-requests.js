(function () {
  const feedback = document.getElementById('request-feedback');
  if (!feedback) return;
  const messages = JSON.parse(feedback.dataset.messages);
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
  document.querySelectorAll('[data-media-request]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      if (form.getAttribute('aria-busy') === 'true') return;
      const button = form.querySelector('button');
      const label = button.textContent;
      button.disabled = true; button.textContent = form.dataset.working;
      form.setAttribute('aria-busy', 'true');
      try {
        const response = await fetch(form.action, {method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: {Accept: 'application/json'}});
        if (response.redirected) throw new Error('Session unavailable');
        const data = await response.json();
        show(data.result || 'portal_requests_unavailable');
      } catch (_) {
        show('portal_requests_unavailable');
      } finally {
        button.disabled = false; button.textContent = label;
        form.removeAttribute('aria-busy');
      }
    });
  });
})();
