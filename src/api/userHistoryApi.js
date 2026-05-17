function apiPath(path) {
  const base = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  return base ? `${base}${path}` : path;
}

function getSessionToken() {
  try {
    const raw = localStorage.getItem("cropperhub_session");
    if (!raw) return "";
    const session = JSON.parse(raw);
    return typeof session?.token === "string" ? session.token : "";
  } catch {
    return "";
  }
}

function authHeader() {
  const token = getSessionToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseError(res) {
  const text = await res.text();
  if (!text) return `Request failed (${res.status})`;
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === "string") return parsed.detail;
  } catch {
    // Fall back to raw text response.
  }
  return text;
}

/**
 * Fetch the full customer history (purchases + returns) behind a suborder id.
 *
 * Normalizes input, hits the premium `/api/history/customer` endpoint and
 * returns the `result` payload produced by the backend helper. Throws an
 * Error with the server-provided detail on failure so the caller can show it.
 */
export async function fetchUserHistoryBySuborder(suborderId) {
  const clean = String(suborderId || "").trim();
  if (!clean) throw new Error("Suborder ID is required.");
  const encoded = encodeURIComponent(clean);
  const res = await fetch(apiPath(`/api/history/customer?suborder_id=${encoded}`), {
    method: "GET",
    headers: authHeader(),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  const result = data?.result;
  return result && typeof result === "object" ? result : null;
}
