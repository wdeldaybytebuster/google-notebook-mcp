/**
 * popup.js — Extension popup script
 *
 * Security invariants:
 *  - Zero raw HTML string assignment with user-derived strings (strict XSS prevention).
 *  - All DOM manipulation via getElementById / createElement / createElementNS / textContent.
 *  - Notebook IDs rendered in --font-mono spans and strictly validated as UUIDv4 on manual entry.
 *  - Zero inline styles; CSS classes only.
 */

const UUID_V4_REGEX = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

const ALLOWED_NOTEBOOK_URL_PREFIXES = [
  'https://notebook.google.com/notebook/',
  'http://notebook.google.com/notebook/',
  'https://notebooklm.google.com/notebook/',
  'http://notebooklm.google.com/notebook/',
];

/**
 * In-memory catalog of discovered + allowlisted notebooks keyed by notebook ID.
 * @type {Map<string, {id: string, title: string, allowed: boolean, mode: 'READ_ONLY' | 'INTERACTIVE', sourceCount?: number}>}
 */
const notebookCatalog = new Map();

// ---------------------------------------------------------------------------
// Strict UUIDv4 & NotebookLM URL Sanitization
// ---------------------------------------------------------------------------

/**
 * Extracts and validates a strict lowercase UUIDv4 notebook ID from raw user input
 * or a NotebookLM URL (`https://notebook.google.com/notebook/<uuid>` or
 * `https://notebooklm.google.com/notebook/<uuid>`).
 *
 * Returns null if malformed or containing path traversal characters.
 *
 * @param {string} rawInput
 * @returns {string | null}
 */
function parseAndValidateNotebookId(rawInput) {
  if (typeof rawInput !== 'string') {
    return null;
  }
  let candidate = rawInput.trim();
  const lowerCandidate = candidate.toLowerCase();
  if (
    !candidate ||
    candidate.includes('..') ||
    candidate.includes('\\') ||
    lowerCandidate.includes('%2e')
  ) {
    return null;
  }
  const looksLikeBareDomain =
    lowerCandidate.startsWith('notebook.google.com/notebook/') ||
    lowerCandidate.startsWith('notebooklm.google.com/notebook/');

  if (candidate.includes('://') || looksLikeBareDomain) {
    const urlStr = candidate.includes('://') ? candidate : 'https://' + candidate;
    const lowerUrl = urlStr.toLowerCase();
    const matchesAllowedPrefix = ALLOWED_NOTEBOOK_URL_PREFIXES.some((prefix) =>
      lowerUrl.startsWith(prefix)
    );
    if (!matchesAllowedPrefix) {
      return null;
    }

    try {
      const parsed = new URL(urlStr);
      if (
        (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') ||
        (parsed.hostname !== 'notebook.google.com' &&
          parsed.hostname !== 'notebooklm.google.com')
      ) {
        return null;
      }
      const pathParts = parsed.pathname.split('/').filter(Boolean);
      if (pathParts.length < 2 || pathParts[0] !== 'notebook') {
        return null;
      }
      candidate = pathParts[1];
    } catch (_err) {
      return null;
    }
  }

  const normalized = candidate.trim().toLowerCase();
  if (!UUID_V4_REGEX.test(normalized)) {
    return null;
  }
  return normalized;
}

/**
 * Normalizes a permission mode string into 'READ_ONLY' or 'INTERACTIVE'.
 * @param {unknown} rawMode
 * @returns {'READ_ONLY' | 'INTERACTIVE'}
 */
function normalizeMode(rawMode) {
  const upper = String(rawMode || 'READ_ONLY').trim().toUpperCase();
  if (upper === 'INTERACTIVE') {
    return 'INTERACTIVE';
  }
  return 'READ_ONLY';
}

// ---------------------------------------------------------------------------
// DOM ready
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', async () => {
  initCopySetupButton();
  initRefreshButton();
  initManualNotebookForm();
  initConnectButton();
  await initStatus();
  await initNotebookList();
});

// ---------------------------------------------------------------------------
// Connection status & Setup Mode
// ---------------------------------------------------------------------------

/**
 * Requests current connection status from the service worker and updates
 * ConnectionHealthBadge, AccountSelector, and state-driven Setup Mode banner.
 */
async function initStatus() {
  let status;
  try {
    status = await chrome.runtime.sendMessage({ type: 'get_status' });
  } catch (_e) {
    status = { ok: false, connected: false };
  }

  const connected = status?.connected === true;
  const extId =
    status?.extensionId ||
    (typeof chrome !== 'undefined' && chrome.runtime?.id) ||
    '<EXTENSION_ID>';

  renderConnectionBadge(connected);
  renderAccountBadge(status?.authuser ?? null);
  renderSetupMode(connected, extId);
}

/**
 * Shows or hides the Setup Mode banner and populates the exact registration command.
 * @param {boolean} connected
 * @param {string} extensionId
 */
function renderSetupMode(connected, extensionId) {
  const banner = document.getElementById('setup-mode-banner');
  const codeEl = document.getElementById('setup-command-code');
  if (!banner) {
    return;
  }

  if (connected) {
    banner.hidden = true;
    return;
  }

  const safeExtId = String(extensionId || '<EXTENSION_ID>').trim();
  if (codeEl) {
    codeEl.textContent = 'python3 setup_native_host.py --extension-id ' + safeExtId;
  }
  banner.hidden = false;
}

/**
 * Wires up the Copy Command button inside the Setup Mode banner.
 */
function initCopySetupButton() {
  const copyBtn = document.getElementById('copy-setup-cmd-btn');
  const codeEl = document.getElementById('setup-command-code');
  if (!copyBtn || !codeEl) {
    return;
  }

  copyBtn.addEventListener('click', async () => {
    const cmdText = codeEl.textContent || '';
    if (!cmdText) {
      return;
    }
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(cmdText);
        copyBtn.textContent = 'Copied!';
        setTimeout(() => {
          copyBtn.textContent = 'Copy Command';
        }, 1500);
      }
    } catch (_err) {
      // Clipboard write unavailable in restricted context
    }
  });
}

/**
 * Updates the connection health badge element.
 * @param {boolean} connected
 */
function renderConnectionBadge(connected) {
  const badge = document.getElementById('connection-health-badge');
  if (!badge) {
    return;
  }

  badge.classList.remove('badge--connected', 'badge--reconnecting', 'badge--disconnected');

  if (connected) {
    badge.classList.add('badge--connected');
    badge.textContent = 'Connected';
  } else {
    badge.classList.add('badge--disconnected');
    badge.textContent = 'Disconnected';
  }
}

/**
 * Renders the active Google account authuser index in the account badge.
 * @param {string | number | null} authuser
 */
function renderAccountBadge(authuser) {
  const badge = document.getElementById('account-badge');
  if (!badge) {
    return;
  }

  if (authuser !== null && authuser !== undefined && authuser !== '') {
    badge.textContent = 'u/' + String(authuser);
    badge.hidden = false;
  } else {
    badge.textContent = '';
    badge.hidden = true;
  }
}

// ---------------------------------------------------------------------------
// NotebookAllowlistCard Checklist & Native Messaging Sync
// ---------------------------------------------------------------------------

/**
 * Merges structured allowlist map or array entries into notebookCatalog.
 * @param {unknown} rawAllowlist
 */
function mergeAllowlistIntoCatalog(rawAllowlist) {
  if (!rawAllowlist) {
    return;
  }

  if (Array.isArray(rawAllowlist)) {
    for (const item of rawAllowlist) {
      if (typeof item === 'string' && item.trim()) {
        const id = item.trim();
        const prev = notebookCatalog.get(id);
        notebookCatalog.set(id, {
          id,
          title: prev?.title || '',
          allowed: true,
          mode: prev?.mode || 'INTERACTIVE',
          sourceCount: prev?.sourceCount,
        });
      } else if (item && typeof item === 'object' && typeof item.id === 'string') {
        const id = item.id.trim();
        if (!id) continue;
        const prev = notebookCatalog.get(id);
        notebookCatalog.set(id, {
          id,
          title: item.title || prev?.title || '',
          allowed: item.allowed !== false,
          mode: normalizeMode(item.mode || prev?.mode || 'READ_ONLY'),
          sourceCount: typeof item.sourceCount === 'number' ? item.sourceCount : prev?.sourceCount,
        });
      }
    }
    return;
  }

  if (typeof rawAllowlist === 'object') {
    for (const [rawId, meta] of Object.entries(rawAllowlist)) {
      const id = String(rawId).trim();
      if (!id) continue;
      const prev = notebookCatalog.get(id);
      const metaObj = meta && typeof meta === 'object' ? meta : {};
      notebookCatalog.set(id, {
        id,
        title: String(metaObj.title || prev?.title || ''),
        allowed: true,
        mode: normalizeMode(metaObj.mode || prev?.mode || 'READ_ONLY'),
        sourceCount: prev?.sourceCount,
      });
    }
  }
}

/**
 * Merges discovered notebooks (objects or raw wXbhsf [title, sources, id] rows) into notebookCatalog.
 * @param {Array<unknown>} discoveredRows
 */
function mergeDiscoveredIntoCatalog(discoveredRows) {
  if (!Array.isArray(discoveredRows)) {
    return;
  }

  for (const entry of discoveredRows) {
    if (Array.isArray(entry)) {
      // wXbhsf row format: row[0] = title, row[2] = notebook UUID
      const id = typeof entry[2] === 'string' ? entry[2].trim() : '';
      const title = typeof entry[0] === 'string' ? entry[0] : '';
      if (!id) continue;
      const prev = notebookCatalog.get(id);
      notebookCatalog.set(id, {
        id,
        title: title || prev?.title || '',
        allowed: Boolean(prev?.allowed),
        mode: prev?.mode || 'READ_ONLY',
        sourceCount: Array.isArray(entry[1]) ? entry[1].length : prev?.sourceCount,
      });
    } else if (entry && typeof entry === 'object' && typeof entry.id === 'string') {
      const id = entry.id.trim();
      if (!id) continue;
      const prev = notebookCatalog.get(id);
      const isAllowed =
        typeof entry.allowed === 'boolean' ? entry.allowed : Boolean(prev?.allowed);
      notebookCatalog.set(id, {
        id,
        title: entry.title || prev?.title || '',
        allowed: isAllowed,
        mode: normalizeMode(entry.mode || prev?.mode || 'READ_ONLY'),
        sourceCount:
          typeof entry.sourceCount === 'number' ? entry.sourceCount : prev?.sourceCount,
      });
    }
  }
}

/**
 * Loads cached and live allowlist + discovered notebooks, then renders checklist.
 */
async function initNotebookList() {
  try {
    if (typeof chrome !== 'undefined' && chrome.storage?.local) {
      const cachedDisc = await chrome.storage.local.get('discovered_notebooks');
      if (Array.isArray(cachedDisc?.discovered_notebooks)) {
        mergeDiscoveredIntoCatalog(cachedDisc.discovered_notebooks);
      }
      const cachedAllow = await chrome.storage.local.get('allowlisted_notebooks');
      if (cachedAllow?.allowlisted_notebooks) {
        mergeAllowlistIntoCatalog(cachedAllow.allowlisted_notebooks);
      }
    }
  } catch (_e) {
    // Ignore local storage errors
  }

  renderNotebookList(Array.from(notebookCatalog.values()));

  try {
    const allowRes = await chrome.runtime.sendMessage({ type: 'get_allowlist' });
    if (allowRes?.ok && allowRes.notebooks) {
      for (const item of notebookCatalog.values()) {
        item.allowed = false;
      }
      mergeAllowlistIntoCatalog(allowRes.notebooks);
    }
  } catch (_e) {
    // Broker offline; keep cached entries
  }

  await discoverNotebooks();
}

/**
 * Triggers live `discover_notebooks` discovery via service_worker.js -> BrokerDaemon / wXbhsf.
 */
async function discoverNotebooks() {
  const refreshBtn = document.getElementById('refresh-notebooks-btn');
  if (refreshBtn) {
    refreshBtn.disabled = true;
  }

  try {
    const res = await chrome.runtime.sendMessage({ type: 'discover_notebooks' });
    if (res?.ok && Array.isArray(res.notebooks)) {
      mergeDiscoveredIntoCatalog(res.notebooks);
    }
  } catch (_e) {
    // Discovery unavailable while disconnected
  } finally {
    if (refreshBtn) {
      refreshBtn.disabled = false;
    }
  }

  renderNotebookList(Array.from(notebookCatalog.values()));
}

/**
 * Serializes all checked notebooks in notebookCatalog to the v2 structured map
 * and persists to allowlist.json via Native Messaging (`update_allowlist`).
 *
 * @returns {Promise<{ok: boolean, error?: {message?: string}}>}
 */
async function persistAllowlist() {
  /** @type {Record<string, {title: string, mode: 'READ_ONLY' | 'INTERACTIVE', manual?: boolean}>} */
  const allowedMap = {};
  for (const nb of notebookCatalog.values()) {
    if (nb.allowed) {
      allowedMap[nb.id] = {
        title: nb.title || '',
        mode: normalizeMode(nb.mode),
        manual: Boolean(nb.manual),
      };
    }
  }

  try {
    const res = await chrome.runtime.sendMessage({
      type: 'update_allowlist',
      notebooks: allowedMap,
    });
    return res || { ok: false };
  } catch (err) {
    return {
      ok: false,
      error: { message: err instanceof Error ? err.message : 'Failed to sync allowlist.' },
    };
  }
}

/**
 * Renders the NotebookAllowlistCard list using pure createElement + textContent.
 * @param {Array<{id: string, title?: string, allowed?: boolean, mode?: 'READ_ONLY' | 'INTERACTIVE', sourceCount?: number}>} notebooks
 */
function renderNotebookList(notebooks) {
  const list = document.getElementById('notebook-list');
  const emptyEl = document.getElementById('notebook-list-empty');

  if (!list) {
    return;
  }

  // Remove previously rendered card elements while preserving #notebook-list-empty
  const existingChildren = Array.from(list.children || []);
  for (const child of existingChildren) {
    if (child.id !== 'notebook-list-empty') {
      if (typeof child.remove === 'function') {
        child.remove();
      } else if (typeof list.removeChild === 'function') {
        list.removeChild(child);
      }
    }
  }

  if (!Array.isArray(notebooks) || notebooks.length === 0) {
    if (emptyEl) {
      emptyEl.hidden = false;
    }
    return;
  }

  if (emptyEl) {
    emptyEl.hidden = true;
  }

  notebooks.forEach((notebook) => {
    const li = createNotebookCard(notebook);
    list.appendChild(li);
  });
}

/**
 * Creates a single interactive NotebookAllowlistCard list item.
 * Strictly uses createElement / createElementNS / textContent.
 *
 * @param {{id: string, title?: string, allowed?: boolean, mode?: 'READ_ONLY' | 'INTERACTIVE', sourceCount?: number}} notebook
 * @returns {HTMLLIElement}
 */
function createNotebookCard(notebook) {
  const li = document.createElement('li');
  li.className = 'notebook-card';

  const currentMode = normalizeMode(notebook.mode);
  const isAllowed = notebook.allowed !== false && Boolean(notebook.allowed ?? true);

  // Checkbox toggle for allowlisting
  const checkbox = document.createElement('input');
  checkbox.type = 'checkbox';
  checkbox.className = 'notebook-card__checkbox';
  checkbox.checked = isAllowed;
  checkbox.setAttribute(
    'aria-label',
    'Allow access to ' + (notebook.title || notebook.id || 'notebook')
  );
  checkbox.addEventListener('change', async () => {
    const entry = notebookCatalog.get(notebook.id) || {
      id: notebook.id,
      title: notebook.title || '',
      allowed: checkbox.checked,
      mode: currentMode,
    };
    entry.allowed = Boolean(checkbox.checked);
    notebookCatalog.set(notebook.id, entry);
    await persistAllowlist(false);
    renderNotebookList(Array.from(notebookCatalog.values()));
  });

  // BookOpen icon (static SVG namespace elements only)
  const iconWrapper = document.createElement('div');
  iconWrapper.className = 'notebook-card__icon';
  iconWrapper.setAttribute('aria-hidden', 'true');
  const svgNS = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(svgNS, 'svg');
  svg.setAttribute('width', '16');
  svg.setAttribute('height', '16');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.75');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  const path1 = document.createElementNS(svgNS, 'path');
  path1.setAttribute('d', 'M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z');
  const path2 = document.createElementNS(svgNS, 'path');
  path2.setAttribute('d', 'M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z');
  svg.appendChild(path1);
  svg.appendChild(path2);
  iconWrapper.appendChild(svg);

  // Body
  const body = document.createElement('div');
  body.className = 'notebook-card__body';

  // Title
  const titleEl = document.createElement('div');
  titleEl.className = 'notebook-card__title';
  titleEl.textContent = notebook.title || 'Untitled Notebook';

  // ID in monospace
  const idEl = document.createElement('span');
  idEl.className = 'notebook-card__id';
  idEl.textContent = notebook.id || '';

  body.appendChild(titleEl);
  body.appendChild(idEl);

  if (typeof notebook.sourceCount === 'number') {
    const sourcesEl = document.createElement('div');
    sourcesEl.className = 'notebook-card__sources';
    sourcesEl.textContent =
      notebook.sourceCount === 1
        ? '1 source'
        : notebook.sourceCount + ' sources';
    body.appendChild(sourcesEl);
  }

  // Granular RBAC Mode Toggle Pills (Read Only vs Interactive)
  const controls = document.createElement('div');
  controls.className = 'notebook-card__controls';

  const roBtn = document.createElement('button');
  roBtn.type = 'button';
  roBtn.className =
    currentMode === 'READ_ONLY'
      ? 'mode-toggle mode-toggle--readonly'
      : 'mode-toggle';
  roBtn.textContent = 'Read Only';
  roBtn.disabled = !isAllowed;
  roBtn.addEventListener('click', async () => {
    const entry = notebookCatalog.get(notebook.id);
    if (!entry) return;
    entry.mode = 'READ_ONLY';
    notebookCatalog.set(notebook.id, entry);
    await persistAllowlist(false);
    renderNotebookList(Array.from(notebookCatalog.values()));
  });

  const rwBtn = document.createElement('button');
  rwBtn.type = 'button';
  rwBtn.className =
    currentMode === 'INTERACTIVE'
      ? 'mode-toggle mode-toggle--interactive'
      : 'mode-toggle';
  rwBtn.textContent = 'Interactive';
  rwBtn.disabled = !isAllowed;
  rwBtn.addEventListener('click', async () => {
    const entry = notebookCatalog.get(notebook.id);
    if (!entry) return;
    entry.mode = 'INTERACTIVE';
    notebookCatalog.set(notebook.id, entry);
    await persistAllowlist(false);
    renderNotebookList(Array.from(notebookCatalog.values()));
  });

  controls.appendChild(roBtn);
  controls.appendChild(rwBtn);
  body.appendChild(controls);

  li.appendChild(checkbox);
  li.appendChild(iconWrapper);
  li.appendChild(body);

  return li;
}

/**
 * Wires up the Sync / Refresh discovery button.
 */
function initRefreshButton() {
  const btn = document.getElementById('refresh-notebooks-btn');
  if (!btn) {
    return;
  }
  btn.addEventListener('click', async () => {
    await discoverNotebooks();
  });
}

/**
 * Wires up the manual Notebook URL / UUID fallback form with strict UUIDv4 sanitization.
 */
function initManualNotebookForm() {
  const form = document.getElementById('manual-notebook-form');
  const inputEl = document.getElementById('manual-notebook-input');
  const titleEl = document.getElementById('manual-notebook-title');
  const modeEl = document.getElementById('manual-notebook-mode');
  const errorEl = document.getElementById('manual-notebook-error');

  if (!form || !inputEl) {
    return;
  }

  form.addEventListener('submit', async (evt) => {
    if (evt && typeof evt.preventDefault === 'function') {
      evt.preventDefault();
    }

    const validatedId = parseAndValidateNotebookId(inputEl.value || '');
    if (!validatedId) {
      if (errorEl) {
        errorEl.textContent =
          'Invalid Notebook URL or UUID. Enter https://notebook.google.com/notebook/<uuid> or a valid 36-char UUID.';
        errorEl.hidden = false;
      }
      return;
    }

    if (errorEl) {
      errorEl.textContent = '';
      errorEl.hidden = true;
    }

    const customTitle = titleEl ? String(titleEl.value || '').trim() : '';
    const selectedMode = normalizeMode(modeEl ? modeEl.value : 'READ_ONLY');
    const prev = notebookCatalog.get(validatedId);

    notebookCatalog.set(validatedId, {
      id: validatedId,
      title: customTitle || prev?.title || '',
      allowed: true,
      mode: selectedMode,
      sourceCount: prev?.sourceCount,
      manual: true,
    });

    const syncRes = await persistAllowlist();
    if (syncRes && syncRes.ok === false) {
      // Rollback notebookCatalog to previous state
      if (prev) {
        notebookCatalog.set(validatedId, prev);
      } else {
        notebookCatalog.delete(validatedId);
      }
      if (errorEl) {
        errorEl.textContent = String(syncRes.error?.message || 'Failed to sync notebook with daemon.');
        errorEl.hidden = false;
      }
    } else {
      inputEl.value = '';
      if (titleEl) {
        titleEl.value = '';
      }
    }

    renderNotebookList(Array.from(notebookCatalog.values()));
  });
}

// ---------------------------------------------------------------------------
// Connect button
// ---------------------------------------------------------------------------

/**
 * Wires up the "Connect this Browser" button.
 */
function initConnectButton() {
  const btn = document.getElementById('connect-button');
  if (!btn) {
    return;
  }

  btn.addEventListener('click', async () => {
    btn.disabled = true;

    const badge = document.getElementById('connection-health-badge');
    if (badge) {
      badge.classList.remove('badge--connected', 'badge--disconnected');
      badge.classList.add('badge--reconnecting');
      badge.textContent = 'Connecting…';
    }

    let response;
    try {
      response = await chrome.runtime.sendMessage({ type: 'initiate_pairing' });
    } catch (_e) {
      response = { ok: false, connected: false };
    }

    const connected = response?.connected === true;
    const extId =
      (typeof chrome !== 'undefined' && chrome.runtime?.id) || '<EXTENSION_ID>';
    renderConnectionBadge(connected);
    renderSetupMode(connected, extId);
    if (connected) {
      await discoverNotebooks();
    }
    btn.disabled = false;
  });
}

// Expose pure validator helper for deterministic unit test verification
globalThis.parseAndValidateNotebookId = parseAndValidateNotebookId;
