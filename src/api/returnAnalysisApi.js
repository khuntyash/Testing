import { fetchWithRetry } from "./taskApi.js";

function apiPath(path) {
  const base = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  return base ? `${base}${path}` : path;
}

function authHeader() {
  try {
    const raw = localStorage.getItem("cropperhub_session");
    if (!raw) return {};
    const session = JSON.parse(raw);
    const token = typeof session?.token === "string" ? session.token : "";
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function parseError(res, fallback) {
  const text = await res.text();
  if (!text) return fallback || `Request failed (${res.status})`;
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === "string") return parsed.detail;
  } catch {
    // Fall back to raw response.
  }
  return text;
}

export async function startReturnAnalysisTask(file, { idempotencyKey, sourcePlatform = "" } = {}) {
  if (!file) {
    throw new Error("Please choose a return Excel file.");
  }
  const data = new FormData();
  data.append("file", file, file.name || "returns.xlsx");
  const headers = authHeader();
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }
  const cleanPlatform = String(sourcePlatform || "").trim().toLowerCase();
  const query = cleanPlatform ? `?platform=${encodeURIComponent(cleanPlatform)}` : "";
  const response = await fetchWithRetry(apiPath(`/api/returns/analysis/start${query}`), {
    method: "POST",
    headers,
    body: data,
  });
  if (!response.ok) {
    throw new Error(await parseError(response, "Failed to start return analysis task."));
  }
  return response.json();
}

