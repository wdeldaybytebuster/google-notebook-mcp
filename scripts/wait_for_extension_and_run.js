// scripts/wait_for_extension_and_run.js
import { execSync, spawn } from "node:child_process";

async function checkExtension() {
  const listRes = await fetch("http://127.0.0.1:9222/json/list");
  const targets = await listRes.json();
  const extTab = targets.find(t => t.url && t.url.includes("chrome://extensions"));
  if (!extTab) {
    console.log("[WATCHER] chrome://extensions tab not found");
    return null;
  }

  return new Promise((resolve) => {
    const ws = new WebSocket(extTab.webSocketDebuggerUrl);
    ws.onopen = () => {
      ws.send(JSON.stringify({
        id: 1,
        method: "Runtime.evaluate",
        params: {
          expression: `(() => {
            const mgr = document.querySelector("extensions-manager");
            const itemList = mgr?.shadowRoot?.querySelector("extensions-item-list");
            const items = itemList?.shadowRoot?.querySelectorAll("extensions-item") || [];
            for (const item of items) {
              const name = item.shadowRoot?.querySelector("#name")?.textContent?.trim() || "";
              if (name.includes("Gemini Notebook MCP")) {
                return { id: item.id, name };
              }
            }
            return null;
          })()`,
          returnByValue: true
        }
      }));
    };
    ws.onmessage = (e) => {
      const m = JSON.parse(e.data);
      if (m.id === 1) {
        ws.close();
        resolve(m.result.result.value);
      }
    };
    ws.onerror = () => {
      ws.close();
      resolve(null);
    };
    setTimeout(() => { ws.close(); resolve(null); }, 2000);
  });
}

async function main() {
  console.log("[WATCHER] Waiting for 'Gemini Notebook MCP Bridge' to be loaded in Chrome Beta...");
  let ext = null;
  for (let i = 0; i < 90; i++) {
    ext = await checkExtension();
    if (ext && ext.id) {
      console.log(`[WATCHER] Found extension! ID: ${ext.id} (${ext.name})`);
      break;
    }
    await new Promise(r => setTimeout(r, 2000));
  }

  if (!ext || !ext.id) {
    console.error("[WATCHER] Timed out waiting for extension to load.");
    process.exit(1);
  }

  // Register native messaging host with the exact extension ID
  console.log(`[WATCHER] Registering Native Messaging Host for ID: ${ext.id}...`);
  execSync(`.venv/bin/python -m mcp_gateway.cli install --extension-id ${ext.id} --browser-config-dir "$HOME/.config/google-chrome-beta"`, { stdio: "inherit" });
  execSync(`.venv/bin/python -m mcp_gateway.cli install --extension-id ${ext.id} --browser-config-dir "$HOME/.config/google-chrome-beta-mcp"`, { stdio: "inherit" });

  console.log("[WATCHER] Running 5-tool live qualification smoke test...");
  const notebookId = process.env.NOTEBOOK_ID || "00000000-0000-0000-0000-000000000001";
  const proc = spawn(".venv/bin/python", ["scripts/live_smoke_test.py", notebookId], { stdio: "inherit" });
  proc.on("close", (code) => {
    process.exit(code);
  });
}

main().catch(err => {
  console.error("[WATCHER ERROR]", err);
  process.exit(1);
});
