// Central place for talking to the backend.
// Change this if your backend runs on a different host/port.
const API_BASE_URL = "http://127.0.0.1:8000";

/**
 * Uploads a .zip file to the backend and returns the FullAnalysisResult JSON.
 * Throws an Error with a readable message on failure.
 */
export async function analyzeProjectZip(zipFile) {
  const formData = new FormData();
  formData.append("file", zipFile);

  let response;
  try {
    response = await fetch(`${API_BASE_URL}/api/scan`, {
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
