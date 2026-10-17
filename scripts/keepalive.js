// scripts/keepalive.js
// Pings ensureNativePort() on the extension service worker every 15 seconds to prevent MV3 idle suspension.
async function keepalive() {
  console.log("[KEEPALIVE] Starting MV3 service worker keepalive daemon...");
  while (true) {
    try {
      const res = await fetch("http://127.0.0.1:9222/json/list");
      const list = await res.json();
      const sw = list.find(t => t.type === "service_worker" && t.url && t.url.includes("service_worker.js"));
      if (sw && sw.webSocketDebuggerUrl) {
        const ws = new WebSocket(sw.webSocketDebuggerUrl);
        await new Promise((resolve) => {
          ws.onopen = () => {
            ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: "ensureNativePort()" } }));
          };
          ws.onmessage = () => { ws.close(); resolve(); };
          ws.onerror = () => { ws.close(); resolve(); };
          setTimeout(() => { ws.close(); resolve(); }, 3000);
        });
      }
    } catch (err) {
      // transient network / chrome restart error
    }
    await new Promise(r => setTimeout(r, 15000));
  }
}

keepalive().catch(console.error);
