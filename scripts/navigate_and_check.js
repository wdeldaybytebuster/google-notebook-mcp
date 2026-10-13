// scripts/navigate_and_check.js
async function main() {
  const listRes = await fetch("http://127.0.0.1:9222/json/list");
  const targets = await listRes.json();
  const pageTarget = targets.find(t => t.type === "page");
  if (!pageTarget) {
    console.error("No page target found");
    process.exit(1);
  }

  console.log("Connecting directly to page:", pageTarget.webSocketDebuggerUrl);
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  let msgId = 1;
  function callMethod(method, params = {}) {
    return new Promise((resolve, reject) => {
      const id = msgId++;
      const onMsg = (event) => {
        const data = JSON.parse(event.data);
        if (data.id === id) {
          ws.removeEventListener("message", onMsg);
          if (data.error) reject(new Error(JSON.stringify(data.error)));
          else resolve(data.result);
        }
      };
      ws.addEventListener("message", onMsg);
      ws.send(JSON.stringify({ id, method, params }));
    });
  }

  console.log("Navigating to https://notebook.google.com/...");
  await callMethod("Page.enable");
  const navRes = await callMethod("Page.navigate", { url: "https://notebook.google.com/" });
  console.log("Navigation initiated:", navRes);

  console.log("Waiting 6 seconds for page to load & execute...");
  await new Promise(r => setTimeout(r, 6000));

  const evalRes = await callMethod("Runtime.evaluate", {
    expression: `(() => {
      const wiz = window.WIZ_global_data || {};
      return {
        url: window.location.href,
        title: document.title,
        ready: typeof wiz.SNlM0e === "string" && wiz.SNlM0e.length > 0,
        email: wiz.oM1Kwf || null,
        snlm0e_length: (wiz.SNlM0e || "").length,
        bodyTextSnippet: (document.body?.innerText || "").slice(0, 300)
      };
    })()`,
    returnByValue: true
  });

  console.log("RESULT:" + JSON.stringify(evalRes.result.value, null, 2));
  ws.close();
}

main().catch(err => {
  console.error("ERROR:", err);
  process.exit(1);
});
