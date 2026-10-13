// scripts/cdp_helper.js
async function cdpCall(wsUrl, method, params = {}) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const id = 1;
    ws.onopen = () => {
      ws.send(JSON.stringify({ id, method, params }));
    };
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.id === id) {
        ws.close();
        if (data.error) reject(new Error(JSON.stringify(data.error)));
        else resolve(data.result);
      }
    };
    ws.onerror = (err) => reject(err);
    setTimeout(() => {
      ws.close();
      reject(new Error("CDP call timed out"));
    }, 10000);
  });
}

async function main() {
  const res = await fetch("http://127.0.0.1:9222/json/list");
  const list = await res.json();
  const extPage = list.find(t => t.url && t.url.includes("chrome://extensions"));
  if (!extPage) {
    console.error("No chrome://extensions page found");
    process.exit(1);
  }
  
  const evalRes = await cdpCall(extPage.webSocketDebuggerUrl, "Runtime.evaluate", {
    expression: `
      (() => {
        const mgr = document.querySelector("extensions-manager");
        const toolbar = mgr?.shadowRoot?.querySelector("extensions-toolbar");
        const devMode = toolbar?.shadowRoot?.querySelector("#devMode");
        if (devMode && !devMode.checked) {
          devMode.click();
        }
        const itemList = mgr?.shadowRoot?.querySelector("extensions-item-list");
        const items = itemList?.shadowRoot?.querySelectorAll("extensions-item") || [];
        const result = [];
        for (const item of items) {
          const name = item.shadowRoot?.querySelector("#name")?.textContent;
          result.push({ id: item.id, name });
        }
        return JSON.stringify({ devModeChecked: devMode?.checked, items: result });
      })()
    `,
    returnByValue: true
  });
  console.log("EVAL_RESULT:" + evalRes.result.value);
}

main().catch(err => {
  console.error("ERROR:", err);
  process.exit(1);
});
