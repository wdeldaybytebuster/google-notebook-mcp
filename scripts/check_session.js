// scripts/check_session.js
async function main() {
  const res = await fetch("http://127.0.0.1:9222/json/version");
  const v = await res.json();
  const ws = new WebSocket(v.webSocketDebuggerUrl);

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  const listRes = await fetch("http://127.0.0.1:9222/json/list");
  const targets = await listRes.json();
  const pageTarget = targets.find(t => t.type === "page");
  if (!pageTarget) {
    console.error("No page target found");
    process.exit(1);
  }

  // Attach to page
  let sessionId = null;
  const attachPromise = new Promise(resolve => {
    const handler = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.result?.sessionId) {
        sessionId = msg.result.sessionId;
        ws.removeEventListener("message", handler);
        resolve(sessionId);
      }
    };
    ws.addEventListener("message", handler);
  });
  ws.send(JSON.stringify({
    id: 1,
    method: "Target.attachToTarget",
    params: { targetId: pageTarget.id, flatten: true }
  }));
  await attachPromise;

  // Navigate to https://notebook.google.com/
  ws.send(JSON.stringify({
    id: 2,
    sessionId,
    method: "Page.navigate",
    params: { url: "https://notebook.google.com/" }
  }));

  // Wait 4 seconds for network / navigation
  await new Promise(r => setTimeout(r, 4000));

  // Evaluate readiness expression
  const evalPromise = new Promise(resolve => {
    const handler = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.id === 3) {
        ws.removeEventListener("message", handler);
        resolve(msg.result);
      }
    };
    ws.addEventListener("message", handler);
  });

  ws.send(JSON.stringify({
    id: 3,
    sessionId,
    method: "Runtime.evaluate",
    params: {
      expression: `(() => {
        const wiz = window.WIZ_global_data || {};
        return {
          url: window.location.href,
          title: document.title,
          ready: typeof wiz.SNlM0e === "string" && wiz.SNlM0e.length > 0,
          email: wiz.oM1Kwf || null,
          authuser: window.location.pathname.match(/\\/u\\/(\\d+)\\//)?.[1] || "0"
        };
      })()`,
      returnByValue: true
    }
  }));

  const evalResult = await evalPromise;
  console.log("SESSION_CHECK_RESULT:" + JSON.stringify(evalResult?.result?.value));
  ws.close();
}

main().catch(err => {
  console.error("ERROR:", err);
  process.exit(1);
});
