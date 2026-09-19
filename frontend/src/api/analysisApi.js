// Central place for talking to the backend.
// Change this if your backend runs on a different host/port.
const API_BASE_URL =  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

/**
 * Uploads a .zip file to the backend and returns the FullAnalysisResult JSON.
 * Throws an Error with a readable message on failure.
 *
 * `includeLow` mirrors the backend's `include_low` query param on
 * /api/scan. Default is false: low-severity findings are still fully
 * computed server-side (and remain look-up-able via /api/explain and
 * /api/chat), but are left out of `issues`/`total_issues` here so the
 * dashboard isn't cluttered with low-priority noise by default. Pass
 * `true` explicitly if you add a "show low severity" toggle later.
 */
export async function analyzeProjectZip(zipFile, includeLow = false) {
  const formData = new FormData();
  formData.append("file", zipFile);

  const url = `${API_BASE_URL}/api/scan?include_low=${includeLow}`;

  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      body: formData,
    });
  } catch (networkError) {
    throw new Error(
      `Could not reach the backend at ${API_BASE_URL}. Is it running? ` +
        `(uvicorn app.main:app --reload)`
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Analysis failed: ${detail}`);
  }

  return response.json();
}

/**
 * Requests the AI explanation for ONE issue. Called on-demand (when the
 * user selects an issue in the dashboard), not eagerly for all issues —
 * that's what made big-project scans slow before.
 */
export async function explainIssue(jobId, issueId) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/explain/${jobId}/${issueId}`, {
      method: "POST",
    });
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Could not generate AI explanation: ${detail}`);
  }

  return response.json();
}

/**
 * Sends one chat message scoped to a specific issue. The backend maintains
 * conversation history server-side (keyed by job_id + issue_id) — we only
 * send the new message, not prior history. Returns the full updated
 * history so the UI can stay in sync.
 */
export async function sendChatMessage(jobId, issueId, message) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/chat/${jobId}/${issueId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Chat failed: ${detail}`);
  }

  return response.json();
}

/**
 * Runs the full plan -> patch -> sandbox-validate fix loop for one issue
 * (POST /api/fix/{job_id}/{issue_id}). Nothing is applied to the real
 * project yet — this only proposes and validates a fix, returning a
 * FixResult the UI can show (attempts, validation notes, success/fail).
 */
export async function requestFix(jobId, issueId) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/fix/${jobId}/${issueId}`, {
      method: "POST",
    });
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Fix failed: ${detail}`);
  }

  return response.json();
}

/**
 * Downloads a .zip of the project with the validated fix for `issueId`
 * actually applied to the files. Calls
 * POST /api/fix/{job_id}/{issue_id}/download, which re-runs the fix loop
 * itself if requestFix() above hasn't been called yet for this issue — so
 * this always works standalone, even without a prior /api/fix call.
 *
 * Triggers a real browser download rather than returning JSON, since the
 * response body is the zip file's bytes.
 */
export async function downloadFixedProject(jobId, issueId) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/fix/${jobId}/${issueId}/download`, {
      method: "POST",
    });
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Could not download the fixed project: ${detail}`);
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `fixed_project_${issueId}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

/**
 * Runs the plan -> patch -> sandbox-validate loop for EVERY issue in the
 * job in one call (POST /api/fix-all/{job_id}) — for when there are too
 * many issues to fix one at a time by hand. Returns a BulkFixResult with
 * per-issue outcomes and fixed/failed/skipped counts. Can take a while on
 * a project with a lot of issues, since each one may involve its own LLM
 * call and its own full re-analysis pass.
 */
export async function requestFixAll(jobId) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/fix-all/${jobId}`, {
      method: "POST",
    });
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Fix all failed: ${detail}`);
  }

  return response.json();
}

/**
 * Kicks off the same bulk fix loop in the backend but returns immediately
 * (POST /api/fix-all/{job_id}/start) instead of blocking until every
 * issue is done. Pair with pollFixAllProgress() below to show live
 * progress instead of one long silent wait. Safe to call again while a
 * run is already in progress — the backend just returns that run's
 * current progress instead of starting a second one.
 */
export async function startFixAll(jobId) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/fix-all/${jobId}/start`, {
      method: "POST",
    });
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Could not start fixing issues: ${detail}`);
  }

  return response.json();
}

/**
 * One poll of GET /api/fix-all/{job_id}/progress — returns
 * { status, total, processed, fixed, failed, skipped, error, result }.
 * "result" is only populated once status is "done". Call this on an
 * interval (see ResultsScreen.jsx's handleFixAll) rather than once.
 */
export async function getFixAllProgress(jobId) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/fix-all/${jobId}/progress`);
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Could not check fix progress: ${detail}`);
  }

  return response.json();
}

/**
 * Downloads a single .zip of the project with EVERY successfully
 * auto-fixed issue applied at once (POST /api/fix-all/{job_id}/download).
 * Runs the bulk fix loop itself first if requestFixAll() hasn't been
 * called yet for this job, so this always works standalone.
 */
export async function downloadAllFixedProject(jobId) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/fix-all/${jobId}/download`, {
      method: "POST",
    });
  } catch (networkError) {
    throw new Error(`Could not reach the backend at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new Error(`Could not download the fixed project: ${detail}`);
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `fixed_project_all_${jobId}.zip`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}