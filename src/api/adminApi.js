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
    // Fallback to raw response.
  }
  return text;
}

const ADMIN_USERS_NAMESPACE = "adminUsers";
const ADMIN_USERS_TTL_MS = 20_000;
const ADMIN_AUDIT_NAMESPACE = "adminRoleAudit";
const ADMIN_AUDIT_TTL_MS = 20_000;
const ADMIN_OCR_NAMESPACE = "adminOcr";
const ADMIN_OCR_TTL_MS = 20_000;
const ADMIN_RETURN_NAMESPACE = "adminReturnAnalysis";
const ADMIN_RETURN_TTL_MS = 20_000;
const ADMIN_JOBS_NAMESPACE = "adminJobs";
const ADMIN_JOBS_TTL_MS = 20_000;
const ADMIN_WALLET_AUDIT_NAMESPACE = "adminWalletAudit";
const ADMIN_WALLET_AUDIT_TTL_MS = 20_000;

export async function fetchAdminMetrics() {
  const res = await fetch(apiPath("/api/admin/metrics"), {
    method: "GET",
    headers: authHeader(),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return data.metrics || null;
}

/**
 * Lists users with optional name/email substring search and pagination.
 * Cached for ~20s and de-duplicated across concurrent callers; pass
 * `bypassCache: true` to force a fresh round-trip.
 *
 * @param {object} [args]
 * @param {string} [args.query]
 * @param {number} [args.limit]
 * @param {number} [args.offset]
 * @param {boolean} [args.bypassCache]
 * @returns {Promise<{ users: Array, total: number }>}
 */
export async function fetchAdminUsers({
  query = "",
  limit = 20,
  offset = 0,
  sort = "default",
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const cleanQuery = (query || "").trim();
  if (cleanQuery) params.set("query", cleanQuery);
  const cleanSort = (sort || "default").trim();
  if (cleanSort && cleanSort !== "default") params.set("sort", cleanSort);

  const cacheKey = buildCacheKey({ query: cleanQuery, limit, offset, sort: cleanSort });

  return cachedRequest({
    namespace: ADMIN_USERS_NAMESPACE,
    key: cacheKey,
    ttlMs: ADMIN_USERS_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/users?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        users: Array.isArray(data.users) ? data.users : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

export async function fetchAdminUsersCursor({
  query = "",
  limit = 20,
  cursor = null,
  sort = "default",
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const cleanQuery = (query || "").trim();
  if (cleanQuery) params.set("query", cleanQuery);
  const cleanSort = (sort || "default").trim();
  if (cleanSort && cleanSort !== "default") params.set("sort", cleanSort);
  if (cursor !== null && cursor !== undefined) params.set("cursor", String(cursor));
  const cacheKey = buildCacheKey({ query: cleanQuery, limit, cursor: cursor ?? "", sort: cleanSort });
  return cachedRequest({
    namespace: `${ADMIN_USERS_NAMESPACE}:cursor`,
    key: cacheKey,
    ttlMs: ADMIN_USERS_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/users/cursor?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        users: Array.isArray(data.users) ? data.users : [],
        total: Number.isFinite(data.total) ? data.total : 0,
        nextCursor:
          typeof data.next_cursor === "number" || data.next_cursor === null
            ? data.next_cursor
            : null,
        hasMore: Boolean(data.has_more),
      };
    },
  });
}

/**
 * Toggles admin role for a user. Invalidates the user-list cache so the
 * next read reflects the change.
 *
 * @param {number} userId
 * @param {boolean} isAdmin
 * @returns {Promise<object>} updated user record
 */
export async function updateAdminUserRole(userId, isAdmin) {
  const res = await fetch(apiPath(`/api/admin/users/${userId}/role`), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ is_admin: Boolean(isAdmin) }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  invalidate(ADMIN_USERS_NAMESPACE);
  invalidate(`${ADMIN_USERS_NAMESPACE}:cursor`);
  invalidate(ADMIN_AUDIT_NAMESPACE);
  invalidate(`${ADMIN_AUDIT_NAMESPACE}:cursor`);
  return data.user || null;
}

export async function updateAdminUsersRoleBulk(userIds, isAdmin) {
  const ids = Array.isArray(userIds) ? userIds : [];
  const res = await fetch(apiPath("/api/admin/users/roles/bulk"), {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({ user_ids: ids, is_admin: Boolean(isAdmin) }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  invalidate(ADMIN_USERS_NAMESPACE);
  invalidate(`${ADMIN_USERS_NAMESPACE}:cursor`);
  invalidate(ADMIN_AUDIT_NAMESPACE);
  invalidate(`${ADMIN_AUDIT_NAMESPACE}:cursor`);
  return Array.isArray(data.users) ? data.users : [];
}

export async function adminCreditUserWallet({ targetUserId = null, targetEmail = "", amount, note = "" } = {}) {
  const payload = {
    target_user_id: targetUserId !== null && targetUserId !== undefined ? Number(targetUserId) : null,
    target_email: String(targetEmail || "").trim(),
    amount: Number(amount || 0),
    note: String(note || ""),
  };
  const res = await fetch(apiPath("/api/admin/wallet/credit"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  invalidate(ADMIN_USERS_NAMESPACE);
  invalidate(`${ADMIN_USERS_NAMESPACE}:cursor`);
  invalidate(ADMIN_WALLET_AUDIT_NAMESPACE);
  return {
    targetUserId: Number(data?.target_user_id || 0),
    wallet: data?.wallet || null,
  };
}

export async function fetchAdminWalletAudit({
  query = "",
  limit = 20,
  offset = 0,
  bypassCache = false,
} = {}) {
  const cleanQuery = (query || "").trim();
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (cleanQuery) params.set("query", cleanQuery);
  const cacheKey = buildCacheKey({ query: cleanQuery, limit, offset });
  return cachedRequest({
    namespace: ADMIN_WALLET_AUDIT_NAMESPACE,
    key: cacheKey,
    ttlMs: ADMIN_WALLET_AUDIT_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/wallet/audit?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        events: Array.isArray(data.events) ? data.events : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

export async function fetchAdminRoleAudit({
  actorQuery = "",
  targetQuery = "",
  fromDate = "",
  toDate = "",
  limit = 20,
  offset = 0,
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const cleanActor = (actorQuery || "").trim();
  const cleanTarget = (targetQuery || "").trim();
  if (cleanActor) params.set("actor_query", cleanActor);
  if (cleanTarget) params.set("target_query", cleanTarget);
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  const cacheKey = buildCacheKey({
    actorQuery: cleanActor,
    targetQuery: cleanTarget,
    fromDate: fromDate || "",
    toDate: toDate || "",
    limit,
    offset,
  });
  return cachedRequest({
    namespace: ADMIN_AUDIT_NAMESPACE,
    key: cacheKey,
    ttlMs: ADMIN_AUDIT_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/role-audit?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        events: Array.isArray(data.events) ? data.events : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

export async function exportAdminRoleAuditCsv({
  actorQuery = "",
  targetQuery = "",
  fromDate = "",
  toDate = "",
  columns = [],
} = {}) {
  const params = new URLSearchParams();
  const cleanActor = (actorQuery || "").trim();
  const cleanTarget = (targetQuery || "").trim();
  if (cleanActor) params.set("actor_query", cleanActor);
  if (cleanTarget) params.set("target_query", cleanTarget);
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  const cleanColumns = Array.isArray(columns) ? columns.filter(Boolean) : [];
  if (cleanColumns.length) params.set("columns", cleanColumns.join(","));
  const res = await fetch(apiPath(`/api/admin/role-audit/export?${params.toString()}`), {
    method: "GET",
    headers: authHeader(),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return await res.blob();
}

export async function fetchAdminRoleAuditCursor({
  actorQuery = "",
  targetQuery = "",
  fromDate = "",
  toDate = "",
  limit = 20,
  cursor = null,
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  const cleanActor = (actorQuery || "").trim();
  const cleanTarget = (targetQuery || "").trim();
  if (cleanActor) params.set("actor_query", cleanActor);
  if (cleanTarget) params.set("target_query", cleanTarget);
  if (fromDate) params.set("from_date", fromDate);
  if (toDate) params.set("to_date", toDate);
  if (cursor !== null && cursor !== undefined) params.set("cursor", String(cursor));
  const cacheKey = buildCacheKey({
    actorQuery: cleanActor,
    targetQuery: cleanTarget,
    fromDate: fromDate || "",
    toDate: toDate || "",
    limit,
    cursor: cursor ?? "",
  });
  return cachedRequest({
    namespace: `${ADMIN_AUDIT_NAMESPACE}:cursor`,
    key: cacheKey,
    ttlMs: ADMIN_AUDIT_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/role-audit/cursor?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        events: Array.isArray(data.events) ? data.events : [],
        total: Number.isFinite(data.total) ? data.total : 0,
        nextCursor:
          typeof data.next_cursor === "number" || data.next_cursor === null
            ? data.next_cursor
            : null,
        hasMore: Boolean(data.has_more),
      };
    },
  });
}

export async function fetchAdminOcrTasks({
  query = "",
  limit = 20,
  offset = 0,
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const cleanQuery = (query || "").trim();
  if (cleanQuery) params.set("query", cleanQuery);
  const cacheKey = buildCacheKey({ query: cleanQuery, limit, offset });
  return cachedRequest({
    namespace: `${ADMIN_OCR_NAMESPACE}:tasks`,
    key: cacheKey,
    ttlMs: ADMIN_OCR_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/ocr/tasks?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        tasks: Array.isArray(data.tasks) ? data.tasks : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

export async function fetchAdminOcrTaskRows({
  taskId,
  query = "",
  limit = 50,
  offset = 0,
  bypassCache = false,
} = {}) {
  const id = encodeURIComponent(String(taskId || ""));
  if (!id) throw new Error("taskId is required");
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const cleanQuery = (query || "").trim();
  if (cleanQuery) params.set("query", cleanQuery);
  const cacheKey = buildCacheKey({ taskId: id, query: cleanQuery, limit, offset });
  return cachedRequest({
    namespace: `${ADMIN_OCR_NAMESPACE}:rows`,
    key: cacheKey,
    ttlMs: ADMIN_OCR_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/ocr/tasks/${id}/rows?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        rows: Array.isArray(data.rows) ? data.rows : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

export async function fetchAdminReturnTasks({
  query = "",
  limit = 20,
  offset = 0,
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const cleanQuery = (query || "").trim();
  if (cleanQuery) params.set("query", cleanQuery);
  const cacheKey = buildCacheKey({ query: cleanQuery, limit, offset });
  return cachedRequest({
    namespace: `${ADMIN_RETURN_NAMESPACE}:tasks`,
    key: cacheKey,
    ttlMs: ADMIN_RETURN_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/returns/tasks?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        tasks: Array.isArray(data.tasks) ? data.tasks : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

export async function fetchAdminReturnTaskRows({
  taskId,
  query = "",
  limit = 50,
  offset = 0,
  bypassCache = false,
} = {}) {
  const id = encodeURIComponent(String(taskId || ""));
  if (!id) throw new Error("taskId is required");
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const cleanQuery = (query || "").trim();
  if (cleanQuery) params.set("query", cleanQuery);
  const cacheKey = buildCacheKey({ taskId: id, query: cleanQuery, limit, offset });
  return cachedRequest({
    namespace: `${ADMIN_RETURN_NAMESPACE}:rows`,
    key: cacheKey,
    ttlMs: ADMIN_RETURN_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/returns/tasks/${id}/rows?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        rows: Array.isArray(data.rows) ? data.rows : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

export async function fetchAdminJobs({
  limit = 20,
  offset = 0,
  bypassCache = false,
} = {}) {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  const cacheKey = buildCacheKey({ limit, offset });
  return cachedRequest({
    namespace: ADMIN_JOBS_NAMESPACE,
    key: cacheKey,
    ttlMs: ADMIN_JOBS_TTL_MS,
    bypassCache,
    fetcher: async () => {
      const res = await fetch(apiPath(`/api/admin/jobs?${params.toString()}`), {
        method: "GET",
        headers: authHeader(),
      });
      if (!res.ok) throw new Error(await parseError(res));
      const data = await res.json();
      return {
        jobs: Array.isArray(data.jobs) ? data.jobs : [],
        total: Number.isFinite(data.total) ? data.total : 0,
      };
    },
  });
}

/** Supported per-platform OCR master values understood by the backend. */
export const ADMIN_OCR_PLATFORMS = Object.freeze(["meesho", "flipkart"]);

/**
 * Download a user's master OCR CSV. When ``platform`` is one of the supported
 * values (e.g. ``meesho``/``flipkart``), the per-platform file is fetched.
 * Without a platform argument (or ``""``) the legacy union endpoint is used,
 * keeping older callers working.
 *
 * @param {number|string} userId
 * @param {string} [platform]
 * @returns {Promise<Blob>}
 */
export async function downloadAdminUserMasterCsv(userId, platform = "") {
  const safeUserId = encodeURIComponent(String(userId || ""));
  if (!safeUserId) throw new Error("userId is required");
  const cleanPlatform = String(platform || "").trim().toLowerCase();
  let url;
  if (cleanPlatform) {
    if (!ADMIN_OCR_PLATFORMS.includes(cleanPlatform)) {
      throw new Error(`Unsupported platform: ${platform}`);
    }
    url = apiPath(
      `/api/admin/users/${safeUserId}/ocr/master/${encodeURIComponent(cleanPlatform)}/download`,
    );
  } else {
    url = apiPath(`/api/admin/users/${safeUserId}/ocr/master/download`);
  }
  const res = await fetch(url, { method: "GET", headers: authHeader() });
  if (!res.ok) throw new Error(await parseError(res));
  return await res.blob();
}

export async function downloadAdminUserSuspiciousCsv(userId, platform = "") {
  const safeUserId = encodeURIComponent(String(userId || ""));
  if (!safeUserId) throw new Error("userId is required");
  const cleanPlatform = String(platform || "").trim().toLowerCase();
  let url;
  if (cleanPlatform) {
    if (!ADMIN_OCR_PLATFORMS.includes(cleanPlatform)) {
      throw new Error(`Unsupported platform: ${platform}`);
    }
    url = apiPath(
      `/api/admin/users/${safeUserId}/risk/suspicious/${encodeURIComponent(cleanPlatform)}/download`,
    );
  } else {
    url = apiPath(`/api/admin/users/${safeUserId}/risk/suspicious/download`);
  }
  const res = await fetch(url, {
    method: "GET",
    headers: authHeader(),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return await res.blob();
}
