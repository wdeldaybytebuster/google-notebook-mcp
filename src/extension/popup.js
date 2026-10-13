/**
 * popup.js — Extension popup script
 *
 * Security invariants:
 *  - No innerHTML with user-derived strings (XSS prevention).
 *  - All DOM manipulation via getElementById / querySelector / createElement.
 *  - Notebook IDs rendered in --font-mono spans.
 *  - Zero inline styles; CSS classes only.
 */

// ---------------------------------------------------------------------------
// DOM ready
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  initStatus();
  initNotebookList();
  initConnectButton();
});

// ---------------------------------------------------------------------------
// Connection status
// ---------------------------------------------------------------------------

/**
 * Requests current connection status from the service worker and updates
 * the ConnectionHealthBadge and AccountSelector (account-badge).
 */
async function initStatus() {
  let status;
  try {
    status = await chrome.runtime.sendMessage({ type: 'get_status' });
  } catch (_e) {
    status = { ok: false, connected: false };
  }

  renderConnectionBadge(status?.connected === true);
  renderAccountBadge(status?.authuser ?? null);
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

  // Remove all state classes first.
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
    // Display only the index number — no email addresses or tokens.
    badge.textContent = 'u/' + String(authuser);
    badge.hidden = false;
  } else {
    badge.textContent = '';
    badge.hidden = true;
  }
}

// ---------------------------------------------------------------------------
// Notebook list
// ---------------------------------------------------------------------------

/**
 * Loads allowlisted notebook IDs from chrome.storage.local and renders cards.
 */
async function initNotebookList() {
  let notebooks = [];

  try {
    const stored = await chrome.storage.local.get('allowlisted_notebooks');
    if (Array.isArray(stored.allowlisted_notebooks)) {
      notebooks = stored.allowlisted_notebooks;
    }
  } catch (_e) {
    // Storage unavailable; leave list empty.
  }

  renderNotebookList(notebooks);
}

/**
 * Renders the notebook list.
 * @param {Array<{id: string, title?: string, sourceCount?: number}>} notebooks
 */
function renderNotebookList(notebooks) {
  const list = document.getElementById('notebook-list');
  const emptyEl = document.getElementById('notebook-list-empty');

  if (!list) {
    return;
  }

  if (notebooks.length === 0) {
    if (emptyEl) {
      emptyEl.hidden = false;
    }
    return;
  }

  // Hide the empty placeholder.
  if (emptyEl) {
    emptyEl.hidden = true;
  }

  notebooks.forEach((notebook) => {
    const li = createNotebookCard(notebook);
    list.appendChild(li);
  });
}

/**
 * Creates a single notebook card list item.
 * Uses only textContent and className — no innerHTML with user-derived strings.
 *
 * @param {{id: string, title?: string, sourceCount?: number}} notebook
 * @returns {HTMLLIElement}
 */
function createNotebookCard(notebook) {
  const li = document.createElement('li');
  li.className = 'notebook-card';

  // BookOpen icon (inline SVG — static markup only, not user-derived)
  const iconWrapper = document.createElement('div');
  iconWrapper.className = 'notebook-card__icon';
  iconWrapper.setAttribute('aria-hidden', 'true');
  // Safe: this SVG string is a static constant, not derived from user data.
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
  // textContent is safe — no HTML injection.
  titleEl.textContent = notebook.title || 'Untitled Notebook';

  // ID in monospace
  const idEl = document.createElement('span');
  idEl.className = 'notebook-card__id';
  idEl.textContent = notebook.id || '';

  // Source count
  const sourcesEl = document.createElement('div');
  sourcesEl.className = 'notebook-card__sources';
  if (typeof notebook.sourceCount === 'number') {
    sourcesEl.textContent =
      notebook.sourceCount === 1
        ? '1 source'
        : notebook.sourceCount + ' sources';
  }

  body.appendChild(titleEl);
  body.appendChild(idEl);
  if (typeof notebook.sourceCount === 'number') {
    body.appendChild(sourcesEl);
  }

  li.appendChild(iconWrapper);
  li.appendChild(body);

  return li;
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

    // Update badge to reconnecting state while attempting.
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

    renderConnectionBadge(response?.connected === true);
    btn.disabled = false;
  });
}
