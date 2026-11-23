// Forward browser failures without sending error text, tokens or user data.
(() => {
  "use strict";
  let sent = 0;
  const requests = new WeakMap();
  const components = new Map([
    ['/dashboard/_now_playing','dashboard_now_playing'],
    ['/dashboard/_next_tasks','dashboard_next_tasks'],
    ['/dashboard/_subscription_summary','dashboard_subscriptions'],
    ['/dashboard/_usage_risk','dashboard_usage_risk'],
    ['/dashboard/_servers','dashboard_servers'],
  ]);
  document.addEventListener('htmx:configRequest', event => {
    const detail = event.detail;
    if (!detail?.headers) return;
    // Random correlation only; no session, visitor or account identifier.
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
      detail.headers['X-VODUM-Request-ID'] = crypto.randomUUID().replaceAll('-','');
    } else if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      // randomUUID needs a secure context; LAN HTTP installations also need correlation.
      detail.headers['X-VODUM-Request-ID'] = Array.from(crypto.getRandomValues(new Uint8Array(16)),
        byte => byte.toString(16).padStart(2,'0')).join('');
    }
  });
  document.addEventListener('htmx:beforeRequest', event => {
    const detail = event.detail;
    if (!detail?.xhr) return;
    let component = 'unknown';
    try {
      const url = new URL(detail.requestConfig?.path || '', window.location.href);
      if (url.origin === window.location.origin) component = components.get(url.pathname) || 'unknown';
    } catch (_) {}
    requests.set(detail.xhr, {started:Date.now(), component,
      request_id:detail.requestConfig?.headers?.['X-VODUM-Request-ID'] || '',
    });
  });
  const scriptPath = /^\/static\/(?:js\/[\w/-]+\.js|vendor\/htmx\/htmx\.min\.js)$/;
  function report(kind, filename, line, context = {}) {
    if (sent >= 5) return;
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    if (!token) return;
    let source = "unknown";
    if (filename === 'inline') source = 'inline';
    else if (filename) {
      try {
        const url = new URL(filename, window.location.href);
        if (url.origin === window.location.origin && scriptPath.test(url.pathname)) {
          source = url.pathname;
        } else if (url.origin === window.location.origin && url.pathname === window.location.pathname) {
          source = 'inline';
        }
      } catch (_) { /* Invalid source is reported as unknown. */ }
    }
    sent += 1;
    const endpoint = window.location.pathname.startsWith("/portal")
      ? "/api/portal/client-errors" : "/api/client-errors";
    const area = window.location.pathname.split('/')[1] || 'dashboard';
    const pages = ['dashboard','monitoring','users','servers','collections','subscriptions','communications','migrations','backup','settings','portal','logs','tasks','about'];
    fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ kind, source, line: Number.isInteger(line) ? line : 0,
        page: pages.includes(area) ? area : 'unknown', ...context }),
      keepalive: true,
    }).catch(() => { /* Network failure cannot be reported over the same network. */ });
  }
  window.addEventListener("error", (event) => {
    // Resource load errors (images, etc.) are handled by their own fallbacks.
    if (event instanceof ErrorEvent) report("javascript", event.filename, event.lineno);
  });
  function scriptLocation(stacks) {
    let inline = [undefined, 0];
    for (const stack of stacks) {
      for (const frame of String(stack || "").split("\n")) {
        const match = frame.match(/(https?:\/\/[^\s)]+):(\d+):\d+/);
        if (!match) continue;
        try {
          const url = new URL(match[1], window.location.href);
          if (url.origin === window.location.origin &&
              scriptPath.test(url.pathname) &&
              url.pathname !== "/static/js/error-reporting.js") {
            return [match[1], Number(match[2])];
          }
          if (url.origin === window.location.origin && url.pathname === window.location.pathname) inline = ['inline',Number(match[2])];
        } catch (_) { /* Inspect the next frame. */ }
      }
    }
    return inline;
  }
  window.addEventListener("unhandledrejection", (event) =>
    report("unhandledrejection", ...scriptLocation([event?.reason?.stack])));
  const originalError = console.error.bind(console);
  console.error = (...args) => {
    originalError(...args);
    // HTMX also emits console errors. Its dedicated event below carries status.
    const htmxEvents = ['htmx:responseError','htmx:sendError','htmx:timeout','htmx:swapError','htmx:targetError'];
    if (htmxEvents.includes(args[0])) return;
    // Extract only a script location, never transmit the error/stack contents.
    const [filename, line] = scriptLocation([
      ...args.filter(arg => arg instanceof Error).map(arg => arg.stack),
      new Error().stack,
    ]);
    // HTMX logs human-readable strings in addition to its error events.
    // Suppress this duplicate, retaining the structured event below.
    if (filename && filename.includes('/static/vendor/htmx/htmx.min.js')) return;
    const operations = new Map([
      ['[vodum] refresh failed:', 'refresh'],
      ['[vodum] runTask failed:', 'run_task'],
      ['[vodum] initTabs failed:', 'init_tabs'],
      ['[vodum] refreshActiveTab failed:', 'refresh_tab'],
      ['[vodum] collection state refresh failed', 'collection_refresh'],
      ['[vodum] saving collection failed', 'collection_save'],
      ['[vodum] queue collection failed', 'collection_queue'],
      ['[vodum] shared collection settings failed', 'collection_settings'],
    ]);
    const operation = operations.get(args[0]);
    report("console_error", filename, line, operation ? {operation} : {});
  };
  for (const name of ['responseError','sendError','timeout','swapError','targetError']) {
    document.addEventListener(`htmx:${name}`, event => {
      const status = event.detail?.xhr?.status;
      const xhr = event.detail?.xhr;
      const tracked = xhr && requests.get(xhr);
      report('htmx', '/static/vendor/htmx/htmx.min.js', 0, {
        operation: `htmx_${name}`,
        http_status: Number.isInteger(status) && status >= 0 && status <= 599 ? status : 0,
        component: tracked?.component || 'unknown',
        request_id: tracked?.request_id || '',
        elapsed_ms: tracked ? Math.min(3600000,Math.max(0,Date.now()-tracked.started)) : 0,
        timeout_ms: Number.isInteger(xhr?.timeout) ? Math.min(3600000,Math.max(0,xhr.timeout)) : 0,
      });
    });
  }
})();
