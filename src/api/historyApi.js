import { buildCacheKey, cachedRequest, invalidate } from "./requestCache.js";

/** Base URL for API in production. Empty = same origin / Vite dev proxy. */
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
    // Fallback to plain text.
  }
  return text;
}

const HISTORY_LIST_NAMESPACE = "historyList";
const HISTORY_DETAIL_NAMESPACE = "historyDetail";
const HISTORY_TTL_MS = 20_000;

export async function fetchCropHistoryJobs({
  platformId = "",
  status = "",
  fromDate = "",
  toDate = "",
  sort = "newest",
  limit = 40,
  offset = 0,
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (platformId) params.set("platform", platformId);
  if (status) params.set("status", status);
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  params.set("sort", sort === "oldest" ? "oldest" : "newest");

  const cacheKey = buildCacheKey({
    platformId,
    status,
    fromDate,
    toDate,
    sort,
    limit,
    offset,
  });

  return cachedRequest({
    namespace: HISTORY_LIST_NAMESPACE,
    key: cacheKey,
    ttlMs: HISTORY_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/history/jobs?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      const jobs = Array.isArray(data.jobs) ? data.jobs : [];
      const apiTotal = Number.isFinite(data.total) ? data.total : jobs.length;
      return {
        jobs,
        total: Math.max(jobs.length, apiTotal),
      };
    },
  });
}

export async function fetchCropHistoryJobDetail(jobId, { bypassCache = false } = {}) {
  const safeId = String(jobId);
  return cachedRequest({
    namespace: HISTORY_DETAIL_NAMESPACE,
    key: safeId,
    ttlMs: HISTORY_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/history/jobs/${safeId}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return data.job || null;
    },
  });
}

/**
 * Drops cached history responses. Call after a new crop job finishes so the
 * next read returns the just-recorded entry instead of stale results.
 */
export function invalidateHistoryCache() {
  invalidate(HISTORY_LIST_NAMESPACE);
  invalidate(HISTORY_DETAIL_NAMESPACE);
}
