// Sequential, bounded POSTs isolate failures and preserve the no-JavaScript forms.
document.addEventListener('DOMContentLoaded', async () => {
  const login = document.querySelector('[data-plex-auto-login="true"]');
  if (login) {
    // Same-tab navigation retains the browser session on mobile. Never auto-loop after a callback error.
    login.requestSubmit();
    return;
  }
  if (document.querySelector('[data-activation-auto]')?.dataset.activationAuto !== 'true') return;
  for (const form of document.querySelectorAll('[data-server-activation]')) {
    const button = form.querySelector('button');
    button.disabled = true;
    form.closest('li').querySelector('[data-server-state]').textContent = form.dataset.workingLabel;
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(form.action, {
        method: 'POST', body: new FormData(form), headers: {Accept: 'application/json'},
        credentials: 'same-origin',
        ...(typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function'
          ? {signal: AbortSignal.timeout(120000)} : {})
      });
      // Authentication failures affect all servers. A transient server/network
      // failure must still allow the other selected servers to be processed.
      if (response.status === 401 || response.status === 403 || response.status === 429) break;
    } catch (_) { /* Continue with the next server; persisted states survive a retry. */ }
    finally { button.disabled = false; form.removeAttribute('aria-busy'); }
  }
  window.location.reload();
});
