// scripts/session_driver.js
class CDPClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl;
    this.ws = null;
    this.nextId = 1;
    this.pending = new Map();
  }

  async connect() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.wsUrl);
      this.ws.onopen = () => resolve();
      this.ws.onerror = (err) => reject(err);
      this.ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id);
          this.pending.delete(msg.id);
          if (msg.error) {
            reject(new Error(JSON.stringify(msg.error)));
          } else {
            resolve(msg.result);
          }
        }
      };
    });
  }

  async send(method, params = {}, sessionId = undefined) {
    const id = this.nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;

    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify(payload));
    });
  }

  close() {
    if (this.ws) this.ws.close();
  }
}

async function main() {
  const v = await fetch("http://127.0.0.1:9222/json/version").then(r => r.json());
  const client = new CDPClient(v.webSocketDebuggerUrl);
  await client.connect();
  console.log("[CDP] Connected to browser debugger.");

  const targetsRes = await client.send("Target.getTargets");
  const pageTarget = targetsRes.targetInfos.find(t => t.type === "page");
  if (!pageTarget) {
    throw new Error("No page target found");
  }
  console.log("[CDP] Found page target:", pageTarget.targetId);

  const attachRes = await client.send("Target.attachToTarget", {
    targetId: pageTarget.targetId,
    flatten: true
  });
  const sessionId = attachRes.sessionId;
  console.log("[CDP] Attached to page with sessionId:", sessionId);

  console.log("[CDP] Navigating to https://notebook.google.com/...");
  await client.send("Page.navigate", { url: "https://notebook.google.com/" }, sessionId);

  console.log("[CDP] Waiting 5 seconds for page load...");
  await new Promise(r => setTimeout(r, 5000));

  const evalRes = await client.send("Runtime.evaluate", {
    expression: `(() => {
      const wiz = window.WIZ_global_data || {};
      return {
        url: window.location.href,
        title: document.title,
        has_wiz: typeof window.WIZ_global_data !== "undefined",
        snlm0e_present: typeof wiz.SNlM0e === "string" && wiz.SNlM0e.length > 0,
        email: wiz.oM1Kwf || null,
        body_text_sample: (document.body ? document.body.innerText.slice(0, 200) : "")
      };
    })()`,
    returnByValue: true
  }, sessionId);

  console.log("[CDP EVAL RESULT]", JSON.stringify(evalRes.result.value, null, 2));

  client.close();
}

main().catch(err => {
  console.error("[FATAL ERROR]", err);
  process.exit(1);
});
