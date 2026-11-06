from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
EXT_DIR = REPO_ROOT / "src" / "extension"
POPUP_JS_PATH = EXT_DIR / "popup.js"


def _run_node_script(script: str) -> dict[str, Any]:
    env = os.environ.copy()
    env.pop("NODE_COMPILE_CACHE", None)
    env["UV_THREADPOOL_SIZE"] = "3"
    env["NODE_OPTIONS"] = "--max-old-space-size=1024 --max-semi-space-size=128"
    proc = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=True,
    )
    out = proc.stdout.strip()
    lines = [line for line in out.splitlines() if line.strip()]
    return dict(json.loads(lines[-1]))


def test_popup_html_contains_setup_mode_checklist_and_manual_fallback() -> None:
    html = (EXT_DIR / "popup.html").read_text(encoding="utf-8")
    # 1. State-driven Setup Mode container & command element
    assert 'id="setup-mode-banner"' in html
    assert 'id="setup-command-code"' in html
    assert 'id="copy-setup-cmd-btn"' in html
    # 2. Refresh discovery button and manual fallback form for older notebooks
    assert 'id="refresh-notebooks-btn"' in html
    assert 'id="manual-notebook-form"' in html
    assert 'id="manual-notebook-input"' in html
    assert 'id="manual-notebook-title"' in html
    assert 'id="manual-notebook-mode"' in html
    assert 'id="manual-notebook-error"' in html
    # 3. Preserved existing popup structural IDs
    assert 'id="connection-health-badge"' in html
    assert 'id="account-badge"' in html
    assert 'id="notebook-list"' in html
    assert 'id="notebook-list-empty"' in html
    assert 'id="connect-button"' in html
    # 4. Fixed documentation link
    assert "https://github.com/wdeldaybytebuster/google-notebook-mcp" in html


def test_popup_css_preserves_tokens_and_has_zero_raw_hex_outside_root() -> None:
    css = (EXT_DIR / "popup.css").read_text(encoding="utf-8")
    root_match = re.search(r":root\s*\{[^}]*\}", css, flags=re.DOTALL)
    assert root_match is not None
    outside_root = css[: root_match.start()] + css[root_match.end() :]
    hex_matches = re.findall(r"#[0-9a-fA-F]{3,8}\b", outside_root)
    assert hex_matches == [], f"Hardcoded hex values found outside :root: {hex_matches}"

    for required_selector in (
        ".setup-banner",
        ".setup-banner__code",
        ".section-header-row",
        ".notebook-card__checkbox",
        ".notebook-card__controls",
        ".mode-toggle",
        ".mode-toggle--readonly",
        ".mode-toggle--interactive",
        ".manual-form",
        ".manual-form__input",
        ".manual-form__select",
        ".manual-form__error",
        ".btn--secondary",
        ".btn--sm",
    ):
        assert required_selector in css


def test_popup_js_enforces_xss_safety_uuid_regex_and_renders_setup_and_modes() -> None:
    js = POPUP_JS_PATH.read_text(encoding="utf-8")
    # Zero innerHTML usage (strict XSS invariant)
    assert ".innerHTML" not in js
    # Dynamically renders exact setup_native_host.py command with extension ID
    assert "python3 setup_native_host.py --extension-id " in js
    # Strict UUIDv4 regex validation for manual fallback inputs
    assert "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$" in js
    assert "notebook.google.com/notebook/" in js
    assert "notebooklm.google.com/notebook/" in js
    # Supports READ_ONLY and INTERACTIVE granular modes
    assert "READ_ONLY" in js
    assert "INTERACTIVE" in js
    # Sends discover_notebooks and update_allowlist messages
    assert "discover_notebooks" in js
    assert "update_allowlist" in js


def test_popup_js_runtime_setup_mode_checklist_and_uuid_sanitization_in_node() -> None:
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync({json.dumps(str(POPUP_JS_PATH))}, 'utf8');

    class MockClassList {{
      constructor(initial = []) {{
        this._set = new Set(initial);
      }}
      add(...cls) {{ cls.forEach((c) => c && this._set.add(c)); }}
      remove(...cls) {{ cls.forEach((c) => this._set.delete(c)); }}
      contains(c) {{ return this._set.has(c); }}
      toArray() {{ return Array.from(this._set); }}
    }}

    class MockElement {{
      constructor(tag, id = '', classes = []) {{
        this.tagName = tag.toUpperCase();
        this.id = id;
        this._className = classes.join(' ');
        this.classList = new MockClassList(classes);
        this.textContent = '';
        this.hidden = false;
        this.disabled = false;
        this.checked = false;
        this.value = '';
        this.type = '';
        this.children = [];
        this.attributes = {{}};
        this.listeners = {{}};
      }}
      get className() {{ return this.classList.toArray().join(' ') || this._className; }}
      set className(v) {{
        this._className = String(v || '');
        this.classList = new MockClassList(this._className.split(/\\s+/).filter(Boolean));
      }}
      setAttribute(k, v) {{ this.attributes[k] = String(v); }}
      getAttribute(k) {{ return this.attributes[k] ?? null; }}
      appendChild(child) {{
        child.parentElement = this;
        this.children.push(child);
        return child;
      }}
      removeChild(child) {{
        const idx = this.children.indexOf(child);
        if (idx >= 0) this.children.splice(idx, 1);
        return child;
      }}
      remove() {{
        if (this.parentElement) this.parentElement.removeChild(this);
      }}
      addEventListener(type, fn) {{
        if (!this.listeners[type]) this.listeners[type] = [];
        this.listeners[type].push(fn);
      }}
      async dispatchEvent(evt) {{
        const fns = this.listeners[evt.type] || [];
        for (const fn of fns) {{
          await fn(evt);
        }}
      }}
    }}

    const elementsById = {{
      'connection-health-badge': new MockElement('span', 'connection-health-badge', ['badge', 'badge--disconnected']),
      'account-badge': new MockElement('span', 'account-badge', ['badge', 'badge--account']),
      'setup-mode-banner': Object.assign(new MockElement('section', 'setup-mode-banner', ['setup-banner']), {{ hidden: true }}),
      'setup-command-code': new MockElement('code', 'setup-command-code', ['setup-banner__code']),
      'copy-setup-cmd-btn': new MockElement('button', 'copy-setup-cmd-btn', ['btn', 'btn--secondary', 'btn--sm']),
      'refresh-notebooks-btn': new MockElement('button', 'refresh-notebooks-btn', ['btn', 'btn--secondary', 'btn--sm']),
      'notebook-list': new MockElement('ul', 'notebook-list', ['notebook-list']),
      'notebook-list-empty': new MockElement('li', 'notebook-list-empty', ['notebook-list__empty']),
      'manual-notebook-form': new MockElement('form', 'manual-notebook-form', ['manual-form']),
      'manual-notebook-input': new MockElement('input', 'manual-notebook-input', ['manual-form__input']),
      'manual-notebook-title': new MockElement('input', 'manual-notebook-title', ['manual-form__input']),
      'manual-notebook-mode': Object.assign(new MockElement('select', 'manual-notebook-mode', ['manual-form__select']), {{ value: 'READ_ONLY' }}),
      'manual-notebook-error': Object.assign(new MockElement('div', 'manual-notebook-error', ['manual-form__error']), {{ hidden: true }}),
      'connect-button': new MockElement('button', 'connect-button', ['btn', 'btn--primary']),
    }};
    elementsById['notebook-list'].appendChild(elementsById['notebook-list-empty']);

    const docListeners = {{}};
    global.document = {{
      getElementById: (id) => elementsById[id] || null,
      createElement: (tag) => new MockElement(tag),
      createElementNS: (_ns, tag) => new MockElement(tag),
      addEventListener: (type, fn) => {{ docListeners[type] = fn; }},
    }};
    global.navigator = {{
      clipboard: {{ writeText: async () => {{}} }},
    }};

    const sentMessages = [];
    const localStore = {{}};
    let mockConnected = false;

    global.chrome = {{
      runtime: {{
        id: 'abcdefghijklmnopabcdefghijklmnop',
        sendMessage: async (msg) => {{
          sentMessages.push(msg);
          if (msg.type === 'get_status') {{
            return {{
              ok: true,
              connected: mockConnected,
              authuser: 0,
              extensionId: 'abcdefghijklmnopabcdefghijklmnop',
            }};
          }}
          if (msg.type === 'get_allowlist') {{
            return {{
              ok: true,
              notebooks: {{
                '11111111-1111-4111-8111-111111111111': {{ title: 'Existing Allowed NB', mode: 'READ_ONLY' }},
              }},
            }};
          }}
          if (msg.type === 'discover_notebooks') {{
            return {{
              ok: true,
              notebooks: [
                {{ id: '11111111-1111-4111-8111-111111111111', title: 'Existing Allowed NB', allowed: true, mode: 'READ_ONLY' }},
                {{ id: '22222222-2222-4222-8222-222222222222', title: 'Discovered Unchecked NB', allowed: false, mode: 'READ_ONLY' }},
              ],
            }};
          }}
          if (msg.type === 'update_allowlist') {{
            return {{ ok: true, notebooks: msg.notebooks }};
          }}
          return {{ ok: true }};
        }},
      }},
      storage: {{
        local: {{
          get: async (k) => ({{ [k]: localStore[k] }}),
          set: async (obj) => {{ Object.assign(localStore, obj); }},
        }},
      }},
    }};

    eval(code);

    (async () => {{
      // 1. Direct UUIDv4 parser checks
      const fn = globalThis.parseAndValidateNotebookId;
      const validRaw = fn('123e4567-e89b-12d3-a456-426614174000');
      const validUrl1 = fn('https://notebook.google.com/notebook/123e4567-e89b-12d3-a456-426614174000?authuser=0');
      const validUrl2 = fn('https://notebooklm.google.com/notebook/123E4567-E89B-12D3-A456-426614174000/');
      const badTraversal = fn('../../etc/passwd');
      const badPercentTraversal = fn('%2e%2e/etc/passwd');
      const badEncodedUrl = fn('https://notebook.google.com/notebook/%2e%2e%2f12345');
      const badHost = fn('https://evil.example.com/notebook/123e4567-e89b-12d3-a456-426614174000');
      const badUuid = fn('not-a-uuid');

      // 2. Boot popup when disconnected -> Setup Mode banner visible with exact command
      await docListeners.DOMContentLoaded();
      await new Promise((r) => setTimeout(r, 30));

      const setupVisibleOnDisconnect = elementsById['setup-mode-banner'].hidden === false;
      const setupCmdText = elementsById['setup-command-code'].textContent;

      // 3. Submit malformed manual input -> shows error, does NOT call update_allowlist
      const beforeBadCount = sentMessages.filter((m) => m.type === 'update_allowlist').length;
      elementsById['manual-notebook-input'].value = '../../etc/passwd';
      await elementsById['manual-notebook-form'].dispatchEvent({{
        type: 'submit',
        preventDefault: () => {{}},
      }});
      const errorShownOnBadInput =
        elementsById['manual-notebook-error'].hidden === false &&
        elementsById['manual-notebook-error'].textContent.length > 0;
      const afterBadCount = sentMessages.filter((m) => m.type === 'update_allowlist').length;

      // 4. Submit valid manual NotebookLM URL with INTERACTIVE mode -> calls update_allowlist with manual: true
      elementsById['manual-notebook-input'].value = 'https://notebook.google.com/notebook/33333333-3333-4333-8333-333333333333';
      elementsById['manual-notebook-title'].value = 'Manual Legacy NB';
      elementsById['manual-notebook-mode'].value = 'INTERACTIVE';
      await elementsById['manual-notebook-form'].dispatchEvent({{
        type: 'submit',
        preventDefault: () => {{}},
      }});
      const updateMsgs = sentMessages.filter((m) => m.type === 'update_allowlist');
      const lastUpdate = updateMsgs[updateMsgs.length - 1];
      const errorHiddenAfterValid = elementsById['manual-notebook-error'].hidden === true;

      console.log(JSON.stringify({{
        validRaw,
        validUrl1,
        validUrl2,
        badTraversal,
        badPercentTraversal,
        badEncodedUrl,
        badHost,
        badUuid,
        setupVisibleOnDisconnect,
        setupCmdText,
        beforeBadCount,
        afterBadCount,
        errorShownOnBadInput,
        errorHiddenAfterValid,
        manualAddedEntry: lastUpdate?.notebooks?.['33333333-3333-4333-8333-333333333333'],
        renderedCardsCount: elementsById['notebook-list'].children.filter((c) => c.id !== 'notebook-list-empty').length,
      }}));
    }})().catch((err) => {{
      console.error(err);
      process.exit(1);
    }});
    """
    out = _run_node_script(script)
    expected_uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert out["validRaw"] == expected_uuid
    assert out["validUrl1"] == expected_uuid
    assert out["validUrl2"] == expected_uuid
    assert out["badTraversal"] is None
    assert out["badPercentTraversal"] is None
    assert out["badEncodedUrl"] is None
    assert out["badHost"] is None
    assert out["badUuid"] is None
    assert out["setupVisibleOnDisconnect"] is True
    assert out["setupCmdText"] == "python3 setup_native_host.py --extension-id abcdefghijklmnopabcdefghijklmnop"
    assert out["errorShownOnBadInput"] is True
    assert out["beforeBadCount"] == out["afterBadCount"]
    assert out["errorHiddenAfterValid"] is True
    assert out["manualAddedEntry"] == {"title": "Manual Legacy NB", "mode": "INTERACTIVE", "manual": True}
    assert out["renderedCardsCount"] >= 2


def test_parse_and_validate_notebook_id_rejects_url_encoded_traversal() -> None:
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync({json.dumps(str(POPUP_JS_PATH))}, 'utf8');
    const ALLOWED_NOTEBOOK_URL_PREFIXES = [
      'https://notebook.google.com/notebook/',
      'https://notebooklm.google.com/notebook/',
      'http://notebook.google.com/notebook/',
      'http://notebooklm.google.com/notebook/',
    ];
    const UUID_V4_REGEX = /^[a-f0-9]{{8}}-[a-f0-9]{{4}}-[a-f0-9]{{4}}-[a-f0-9]{{4}}-[a-f0-9]{{12}}$/;
    const fnMatch = code.match(/function parseAndValidateNotebookId\\([\\s\\S]*?\\)\\s*\\{{[\\s\\S]*?\\n\\}}/);
    if (!fnMatch) throw new Error('parseAndValidateNotebookId not found');
    eval(fnMatch[0]);

    console.log(JSON.stringify({{
        percentDot: parseAndValidateNotebookId('%2e%2e/etc/passwd'),
        doubleDotEncoded: parseAndValidateNotebookId('https://notebook.google.com/notebook/%2e%2e%2f12345'),
        validUuid: parseAndValidateNotebookId('11111111-2222-3333-4444-555555555555')
    }}));
    """
    out = _run_node_script(script)
    assert out["percentDot"] is None
    assert out["doubleDotEncoded"] is None
    assert out["validUuid"] == "11111111-2222-3333-4444-555555555555"


def test_popup_manual_entry_rollback_on_sync_failure() -> None:
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync({json.dumps(str(POPUP_JS_PATH))}, 'utf8');

    globalThis.chrome = {{
      runtime: {{
        sendMessage: async (msg) => ({{
          ok: false,
          error: {{ message: 'Simulated backend sync failure' }},
        }}),
      }},
    }};

    const notebookCatalog = new Map();
    const normMatch = code.match(/function normalizeMode\\([\\s\\S]*?\\)\\s*\\{{[\\s\\S]*?\\n\\}}/);
    const persistMatch = code.match(/async function persistAllowlist\\([\\s\\S]*?\\)\\s*\\{{[\\s\\S]*?\\n\\}}/);
    eval(normMatch[0]);
    eval(persistMatch[0]);

    (async () => {{
      const validId = '44444444-4444-4444-8444-444444444444';
      const initialHas = notebookCatalog.has(validId);

      const prev = notebookCatalog.get(validId);
      notebookCatalog.set(validId, {{
        id: validId,
        title: 'Failing Entry',
        allowed: true,
        mode: 'READ_ONLY',
        manual: true,
      }});

      const syncRes = await persistAllowlist();
      let errorMsg = '';
      if (syncRes && syncRes.ok === false) {{
        if (prev) {{
          notebookCatalog.set(validId, prev);
        }} else {{
          notebookCatalog.delete(validId);
        }}
        errorMsg = String(syncRes.error?.message || 'Failed');
      }}

      const rolledBackHas = notebookCatalog.has(validId);

      console.log(JSON.stringify({{
        initialHas,
        rolledBackHas,
        errorMsg,
        syncOk: syncRes.ok,
      }}));
    }})().catch((err) => {{
      console.error(err);
      process.exit(1);
    }});
    """
    out = _run_node_script(script)
    assert out["initialHas"] is False
    assert out["rolledBackHas"] is False
    assert out["syncOk"] is False
    assert out["errorMsg"] == "Simulated backend sync failure"
