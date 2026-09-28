/* Only top-level workspaces own the CLI server; dataset iframes do not. */
(() => {
  if (window.top !== window.self) return;
  let id = crypto.randomUUID(), connected = false, failures = 0, finished = false;
  function showStopped() {
    if (finished) return;
    finished = true;
    clearInterval(timer);
    // Browsers may refuse this for tabs not opened by script.
    window.close();
    const panel = document.createElement('div');
    panel.setAttribute('role', 'alert');
    panel.style.cssText = 'position:fixed;inset:0;z-index:100000;background:#f4f8f6;display:grid;place-content:center;padding:32px;color:#23413b;font:18px system-ui';
    panel.textContent = 'Processing server stopped. You can close this tab. Restart the server and reload this page to begin a new session.';
    document.body.append(panel);
  }
  async function poll() {
    if (finished) return;
    try {
      const response = await fetch('/api/browser-session', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({client: id}), cache: 'no-store',
        signal: AbortSignal.timeout(5000)
      });
      if (!response.ok) return; // Other launchers may not enable automatic shutdown.
      const state = await response.json();
      if (!state.enabled) return;
      connected = true; failures = 0;
      if (state.stopping) showStopped();
    } catch (_) {
      if (connected && ++failures >= 3) showStopped();
    }
  }
  window.addEventListener('pagehide', () => {
    navigator.sendBeacon('/api/browser-session', new Blob([
      JSON.stringify({client: id, leaving: true})
    ], {type: 'application/json'}));
  });
  window.addEventListener('pageshow', event => {
    if (event.persisted) { id = crypto.randomUUID(); poll(); }
  });
  const timer = setInterval(poll, 2000);
  poll();
})();
