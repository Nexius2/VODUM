// Forward browser failures without sending error text, tokens or user data.
(() => {
  "use strict";
  let sent = 0;
  function report(kind, filename, line) {
    if (sent >= 5) return;
    const token = document.querySelector('meta[name="csrf-token"]')?.content;
    if (!token) return;
    let source = "unknown";
    if (filename) {
      try {
        const url = new URL(filename, window.location.href);
        if (url.origin === window.location.origin && /^\/static\/js\/[\w/-]+\.js$/.test(url.pathname)) {
          source = url.pathname;
        }
      } catch (_) { /* Invalid source is reported as unknown. */ }
    }
    sent += 1;
    const endpoint = window.location.pathname.startsWith("/portal")
      ? "/api/portal/client-errors" : "/api/client-errors";
    fetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ kind, source, line: Number.isInteger(line) ? line : 0 }),
      keepalive: true,
    }).catch(() => { /* Network failure cannot be reported over the same network. */ });
  }
  window.addEventListener("error", (event) => {
    // Resource load errors (images, etc.) are handled by their own fallbacks.
    if (event instanceof ErrorEvent) report("javascript", event.filename, event.lineno);
  });
  window.addEventListener("unhandledrejection", () => report("unhandledrejection"));
  const originalError = console.error.bind(console);
  console.error = (...args) => {
    originalError(...args);
    // Extract only a script location, never transmit the error/stack contents.
    const stack = new Error().stack || "";
    let filename;
    let line = 0;
    for (const frame of stack.split("\n")) {
      const match = frame.match(/(https?:\/\/[^\s)]+):(\d+):\d+/);
      if (match && !match[1].includes("/js/error-reporting.js")) {
        filename = match[1];
        line = Number(match[2]);
        break;
      }
    }
    report("console_error", filename, line);
  };
})();
