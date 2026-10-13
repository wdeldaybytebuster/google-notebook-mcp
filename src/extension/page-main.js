/**
 * page-main.js — Injected into the MAIN world via chrome.scripting.executeScript.
 *
 * Running in the MAIN world gives this script access to window.WIZ_global_data,
 * which contains page-resident CSRF and session identifiers used to construct
 * authenticated fetch() calls. These values NEVER appear in postMessage results
 * returned to content_script.js or the service worker.
 *
 * Security invariants:
 *  - SNlM0e, FdrFJe, cookie values, ya29 tokens, and raw HTTP response headers
 *    MUST NOT appear in any postMessage result or console output.
 *  - Auth context is consumed locally within each function call only.
 *  - Zero console.log / console.error calls that reference token values.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BATCHEXECUTE_URL =
  'https://notebook.google.com/_/LabsTailwindUi/data/batchexecute';
const QUERY_URL =
  'https://notebook.google.com/_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed';

// ---------------------------------------------------------------------------
// Auth context — values remain in page scope, never forwarded
// ---------------------------------------------------------------------------

/**
 * Reads page-resident auth identifiers from WIZ_global_data.
 * The returned object stays inside page-main.js; it is NEVER posted back
 * to content_script or the service worker.
 *
 * @returns {{ snlm0e: string, fdrfje: string, authuser: number, accountEmail: string }}
 */
function getAuthContext() {
  const wiz = window.WIZ_global_data ?? {};

  const snlm0e = typeof wiz.SNlM0e === 'string' ? wiz.SNlM0e : '';
  const fdrfje = typeof wiz.FdrFJe === 'string' ? wiz.FdrFJe : '';
  const accountEmail = typeof wiz.oM1Kwf === 'string' ? wiz.oM1Kwf : '';

  // Extract /u/{N}/ from the current pathname; default to 0.
  const match = window.location.pathname.match(/\/u\/(\d+)\//);
  const authuser = match ? parseInt(match[1], 10) : 0;

  return Object.freeze({ snlm0e, fdrfje, authuser, accountEmail });
}

// ---------------------------------------------------------------------------
// batchexecute
// ---------------------------------------------------------------------------

/**
 * Executes a batchexecute RPC via in-browser fetch().
 * The CSRF token (snlm0e) is used to construct the form body but is
 * NEVER included in the returned result object.
 *
 * @param {string} rpcId
 * @param {string} paramsJson
 * @param {string | null} notebookId
 * @returns {Promise<{ok: true, body: string} | {ok: false, error: {code: string, message: string, retryable: boolean}}>}
 */
async function executeBatchexecute(rpcId, paramsJson, notebookId) {
  const auth = getAuthContext();
  if (!auth.snlm0e) {
    return {
      ok: false,
      error: {
        code: 'CSRF_MISSING',
        message: 'CSRF token (SNlM0e) not available on page.',
        retryable: true,
      },
    };
  }

  // Build the URL; append authuser only when it is non-zero.
  let url = BATCHEXECUTE_URL;
  const urlParams = new URLSearchParams();
  if (auth.authuser > 0) {
    urlParams.set('authuser', String(auth.authuser));
  }
  const qs = urlParams.toString();
  if (qs) {
    url = url + '?' + qs;
  }

  // Build form body. The at= field carries snlm0e (CSRF); it is consumed here only.
  const body = new URLSearchParams();
  body.set('f.req', JSON.stringify([[[rpcId, paramsJson, null, 'generic']]]));
  body.set('at', auth.snlm0e);

  try {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'X-Same-Domain': '1',
      },
      body: body.toString(),
    });

    const text = await response.text();

    // Strip anti-XSSI prefix.
    const stripped = text.startsWith(')]}\'\\n')
      ? text.slice(5)
      : text.startsWith(')]}\'')
      ? text.slice(4)
      : text;

    return { ok: true, body: stripped };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'FETCH_ERROR',
        message: err instanceof Error ? err.message : 'Unknown fetch error',
        retryable: true,
      },
    };
  }
}

// ---------------------------------------------------------------------------
// query_stream
// ---------------------------------------------------------------------------

/**
 * Submits a query to the streaming GenerateFreeFormStreamed endpoint.
 * Reads the full streamed response body before returning.
 * Auth values are consumed locally; they do not appear in the result.
 *
 * @param {string} paramsJson
 * @returns {Promise<{ok: true, body: string} | {ok: false, error: {code: string, message: string, retryable: boolean}}>}
 */
async function executeQueryStream(paramsJson) {
  const auth = getAuthContext();
  if (!auth.snlm0e) {
    return {
      ok: false,
      error: {
        code: 'CSRF_MISSING',
        message: 'CSRF token (SNlM0e) not available on page.',
        retryable: true,
      },
    };
  }

  const body = new URLSearchParams();
  body.set('f.req', JSON.stringify([null, paramsJson]));
  body.set('at', auth.snlm0e);

  const urlParams = new URLSearchParams();
  if (auth.authuser > 0) {
    urlParams.set('authuser', String(auth.authuser));
  }
  const qs = urlParams.toString();
  const url = qs ? QUERY_URL + '?' + qs : QUERY_URL;

  try {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'X-Same-Domain': '1',
      },
      body: body.toString(),
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      fullText += decoder.decode(value, { stream: true });
    }
    // Flush the decoder.
    fullText += decoder.decode();

    // Strip anti-XSSI prefix.
    const stripped = fullText.startsWith(')]}\'\\n')
      ? fullText.slice(5)
      : fullText.startsWith(')]}\'')
      ? fullText.slice(4)
      : fullText;

    return { ok: true, body: stripped };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'STREAM_ERROR',
        message: err instanceof Error ? err.message : 'Unknown stream error',
        retryable: true,
      },
    };
  }
}

// ---------------------------------------------------------------------------
// scotty_upload
// ---------------------------------------------------------------------------

/**
 * Performs a Scotty resumable upload in two steps:
 *   1. POST /upload/_/ with x-goog-upload-command: start → obtains session URL.
 *   2. POST raw bytes to session URL with x-goog-upload-command: upload, finalize.
 *
 * Session URLs are used inline and are NOT forwarded to the service worker.
 *
 * @param {string} sourceId
 * @param {string} filename
 * @param {string} notebookId
 * @param {string} fileBase64       Base64-encoded file bytes.
 * @param {number} authuserOverride Optional authuser index (falls back to getAuthContext).
 * @returns {Promise<{ok: true, sourceId: string} | {ok: false, error: {code: string, message: string, retryable: boolean}}>}
 */
async function executeScottyUpload(sourceId, filename, notebookId, fileBase64, authuserOverride) {
  const auth = getAuthContext();
  const authuser = typeof authuserOverride === 'number' ? authuserOverride : auth.authuser;

  // Decode base64 to Uint8Array.
  let fileBytes;
  try {
    const binary = atob(fileBase64);
    fileBytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      fileBytes[i] = binary.charCodeAt(i);
    }
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'DECODE_ERROR',
        message: 'Failed to decode file bytes.',
        retryable: false,
      },
    };
  }

  const uploadInitUrl =
    'https://notebook.google.com/upload/_/LabsTailwindUi/feeds/upload/create_session/interactive/media/?authuser=' +
    encodeURIComponent(String(authuser));

  // Step 1: Register upload intent and obtain session URL.
  let sessionUrl;
  try {
    const initResponse = await fetch(uploadInitUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'X-Goog-Upload-Command': 'start',
        'X-Goog-Upload-Header-Content-Length': String(fileBytes.byteLength),
        'X-Goog-Upload-Header-Content-Type': 'application/octet-stream',
        'X-Goog-Upload-Protocol': 'resumable',
        'X-Same-Domain': '1',
        'X-Goog-Authuser': String(authuser),
      },
      body: JSON.stringify({
        PROJECT_ID: notebookId,
        SOURCE_NAME: filename,
        SOURCE_ID: sourceId,
        sourceId,
        notebookId,
        filename,
      }),
    });

    // Session URL is in the x-goog-upload-url response header; consume it locally.
    sessionUrl =
      initResponse.headers.get('x-goog-upload-url') ||
      initResponse.headers.get('X-Goog-Upload-URL');
    if (!sessionUrl) {
      return {
        ok: false,
        error: {
          code: 'UPLOAD_INIT_ERROR',
          message: 'No upload session URL returned.',
          retryable: true,
        },
      };
    }
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'UPLOAD_INIT_ERROR',
        message: err instanceof Error ? err.message : 'Upload init failed.',
        retryable: true,
      },
    };
  }

  // Step 2: Stream bytes to the session URL.
  try {
    await fetch(sessionUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-Goog-Upload-Command': 'upload, finalize',
        'X-Goog-Upload-Offset': '0',
      },
      body: fileBytes,
    });

    return { ok: true, sourceId };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'UPLOAD_STREAM_ERROR',
        message: err instanceof Error ? err.message : 'Upload stream failed.',
        retryable: true,
      },
    };
  }
}

// ---------------------------------------------------------------------------
// Command dispatcher — window.addEventListener('message')
// ---------------------------------------------------------------------------

window.addEventListener('message', async (event) => {
  // Accept only messages from our own page (content_script relay).
  if (event.source !== window) {
    return;
  }

  const msg = event.data;
  if (!msg || msg.source !== 'mcp_bridge_cmd') {
    return;
  }

  const { command, requestId, payload } = msg;

  if (!command || !requestId) {
    return;
  }

  // Verify expected account email if supplied by caller.
  if (payload?.expectedEmail) {
    const auth = getAuthContext();
    if (auth.accountEmail && auth.accountEmail.toLowerCase() !== payload.expectedEmail.toLowerCase()) {
      window.postMessage(
        {
          source: 'page_main_result',
          requestId,
          result: {
            ok: false,
            error: {
              code: 'PERMISSION_DENIED',
              message: 'Account email mismatch: active Google profile does not match expected email.',
              retryable: false,
            },
          },
        },
        '*'
      );
      return;
    }
  }

  let result;
  try {
    switch (command) {
      case 'batchexecute':
        result = await executeBatchexecute(
          payload.rpcId,
          payload.paramsJson,
          payload.notebookId ?? null
        );
        break;

      case 'query_stream':
        result = await executeQueryStream(payload.paramsJson);
        break;

      case 'scotty_upload':
        result = await executeScottyUpload(
          payload.sourceId,
          payload.filename,
          payload.notebookId,
          payload.fileBase64,
          payload.authuser
        );
        break;

      default:
        result = {
          ok: false,
          error: { code: 'UNKNOWN_COMMAND', message: 'Unrecognised command.', retryable: false },
        };
    }
  } catch (err) {
    result = {
      ok: false,
      error: {
        code: 'DISPATCH_ERROR',
        message: err instanceof Error ? err.message : 'Dispatch error.',
        retryable: false,
      },
    };
  }

  // Post result back. CRITICAL: result must never contain SNlM0e, cookie values,
  // ya29 tokens, or raw HTTP response headers.
  window.postMessage(
    {
      source: 'page_main_result',
      requestId,
      result,
    },
    '*'
  );
});

// ---------------------------------------------------------------------------
// Initial ready signal — notify content_script that page-main is live
// ---------------------------------------------------------------------------

(function sendReadySignal() {
  const auth = getAuthContext();
  // Only the authuser index (a number) is included — no tokens.
  window.postMessage(
    {
      source: 'page_main_result',
      type: 'ready',
      authuser: auth.authuser,
    },
    '*'
  );
})();
