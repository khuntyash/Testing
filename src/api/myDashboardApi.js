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
    // Fall back to plain text body.
  }
  return text;
}

const EMPTY_DASHBOARD = Object.freeze({
  profile: {
    id: 0,
    name: "",
    email: "",
    is_admin: false,
    created_at: "",
  },
  summary: {
    total_jobs: 0,
    success_jobs: 0,
    failed_jobs: 0,
    processing_jobs: 0,
    pending_jobs: 0,
    total_input_pages: 0,
    total_output_labels: 0,
    total_input_files: 0,
    jobs_today: 0,
    jobs_7d: 0,
    last_activity_at: "",
    suspicious_pages_total: 0,
    pincode_pages_total: 0,
    normal_pages_total: 0,
    premium_labels_billed: 0,
  },
  platforms: [],
  recent_jobs: [],
  manual_high_risk: {
    customers_total: 0,
    suborders_total: 0,
    customers_7d: 0,
    suborders_7d: 0,
  },
});

function normalizeSummary(raw) {
  const base = { ...EMPTY_DASHBOARD.summary };
  if (!raw || typeof raw !== "object") return base;
  for (const key of Object.keys(base)) {
    const value = raw[key];
    if (key === "last_activity_at") {
      base[key] = typeof value === "string" ? value : "";
    } else {
      const num = Number(value);
      base[key] = Number.isFinite(num) ? Math.max(0, Math.trunc(num)) : 0;
    }
  }
  return base;
}

function normalizePlatformEntry(raw) {
  if (!raw || typeof raw !== "object") return null;
  const out = {
    platform: typeof raw.platform === "string" && raw.platform ? raw.platform : "unknown",
    total_jobs: 0,
    success_jobs: 0,
    failed_jobs: 0,
    processing_jobs: 0,
    pending_jobs: 0,
    total_input_pages: 0,
    total_output_labels: 0,
    total_input_files: 0,
    suspicious_buyers_total: 0,
    suspicious_pages_total: 0,
    pincode_pages_total: 0,
    normal_pages_total: 0,
    premium_labels_billed: 0,
    last_run_at: typeof raw.last_run_at === "string" ? raw.last_run_at : "",
  };
  for (const key of Object.keys(out)) {
    if (key === "platform" || key === "last_run_at") continue;
    const num = Number(raw[key]);
    out[key] = Number.isFinite(num) ? Math.max(0, Math.trunc(num)) : 0;
  }
  return out;
}

function normalizeRecentJob(raw) {
  if (!raw || typeof raw !== "object") return null;
  return {
    id: Number(raw.id) || 0,
    platform: typeof raw.platform === "string" ? raw.platform : "",
    status: typeof raw.status === "string" ? raw.status : "",
    created_at: typeof raw.created_at === "string" ? raw.created_at : "",
    finished_at: typeof raw.finished_at === "string" ? raw.finished_at : "",
    duration_ms: Number(raw.duration_ms) || 0,
    total_input_pages: Number(raw.total_input_pages) || 0,
    total_output_labels: Number(raw.total_output_labels) || 0,
    total_input_files: Number(raw.total_input_files) || 0,
    layout: typeof raw.layout === "string" ? raw.layout : "",
    sort_by: typeof raw.sort_by === "string" ? raw.sort_by : "",
    error_message: typeof raw.error_message === "string" ? raw.error_message : "",
    download_available: Boolean(raw.download_available),
  };
}

function normalizeManualHighRisk(raw) {
  const base = { ...EMPTY_DASHBOARD.manual_high_risk };
  if (!raw || typeof raw !== "object") return base;
  for (const key of Object.keys(base)) {
    const num = Number(raw[key]);
    base[key] = Number.isFinite(num) ? Math.max(0, Math.trunc(num)) : 0;
  }
  return base;
}

function normalizeProfile(raw) {
  const base = { ...EMPTY_DASHBOARD.profile };
  if (!raw || typeof raw !== "object") return base;
  base.id = Number(raw.id) || 0;
  base.name = typeof raw.name === "string" ? raw.name : "";
  base.email = typeof raw.email === "string" ? raw.email : "";
  base.is_admin = Boolean(raw.is_admin);
  base.created_at = typeof raw.created_at === "string" ? raw.created_at : "";
  return base;
}

/**
 * Fetch the per-user dashboard payload. Always resolves to a fully shaped
 * object so callers never have to null-check nested fields. Throws an Error
 * with the server-provided detail when the API responds non-OK.
 */
export async function fetchMyDashboard({ recentLimit = 5 } = {}) {
  const params = new URLSearchParams();
  params.set("recent_limit", String(Math.max(1, Math.min(25, Number(recentLimit) || 5))));
  const res = await fetch(apiPath(`/api/me/dashboard?${params.toString()}`), {
    method: "GET",
    headers: authHeader(),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  const data = await res.json();
  return {
    profile: normalizeProfile(data?.profile),
    summary: normalizeSummary(data?.summary),
    platforms: Array.isArray(data?.platforms)
      ? data.platforms.map(normalizePlatformEntry).filter(Boolean)
      : [],
    recent_jobs: Array.isArray(data?.recent_jobs)
      ? data.recent_jobs.map(normalizeRecentJob).filter(Boolean)
      : [],
    manual_high_risk: normalizeManualHighRisk(data?.manual_high_risk),
  };
}

export const EMPTY_USER_DASHBOARD = EMPTY_DASHBOARD;
