/**
 * Lightweight in-memory cache with TTL + in-flight request deduping.
 *
 * Designed for read-only GET helpers (history list, admin list, etc.) that
 * are safe to share across rapid re-renders. Mutations (PATCH/POST) should
 * call `invalidate()` (or pass `{ bypassCache: true }` on the next fetch)
 * so subsequent reads see fresh data.
 *
 * Caches are scoped per namespace so different endpoints never collide.
 */

const NAMESPACES = new Map();

function getSessionScopeKey() {
  try {
    const raw = localStorage.getItem("cropperhub_session");
    if (!raw) return "anonymous";
    const session = JSON.parse(raw);
    const stableIdentity =
      session?.id ??
      session?.userId ??
      session?.uid ??
      (typeof session?.email === "string" ? session.email.trim().toLowerCase() : "");
    const normalized = String(stableIdentity || "").trim().toLowerCase();
    return normalized ? encodeURIComponent(normalized) : "anonymous";
  } catch {
    return "anonymous";
  }
}

function getNamespace(name) {
  let ns = NAMESPACES.get(name);
  if (!ns) {
    ns = { entries: new Map(), inflight: new Map() };
    NAMESPACES.set(name, ns);
  }
  return ns;
}

function isFresh(entry, ttlMs) {
  if (!entry) return false;
  if (typeof entry.expiresAt !== "number") return false;
  return entry.expiresAt > Date.now();
}

/**
 * @param {object} args
 * @param {string} args.namespace - logical group (e.g. "history", "adminUsers")
 * @param {string} args.key - canonical cache key, usually a serialized query
 * @param {number} args.ttlMs - how long a successful response stays fresh
 * @param {boolean} [args.bypassCache] - skip cache lookup but still store the new value
 * @param {() => Promise<any>} args.fetcher - underlying network request
 */
export async function cachedRequest({ namespace, key, ttlMs, bypassCache = false, fetcher }) {
  const ns = getNamespace(namespace);

  if (!bypassCache) {
    const hit = ns.entries.get(key);
    if (isFresh(hit, ttlMs)) {
      return hit.value;
    }
  }

  const pending = ns.inflight.get(key);
  if (pending) {
    return pending;
  }

  const promise = (async () => {
    try {
      const value = await fetcher();
      ns.entries.set(key, { value, expiresAt: Date.now() + Math.max(0, ttlMs) });
      return value;
    } finally {
      ns.inflight.delete(key);
    }
  })();
  ns.inflight.set(key, promise);
  return promise;
}

/**
 * Clears cached entries for a namespace. With no key, clears the entire namespace.
 */
export function invalidate(namespace, key) {
  const ns = NAMESPACES.get(namespace);
  if (!ns) return;
  if (typeof key === "string") {
    ns.entries.delete(key);
  } else {
    ns.entries.clear();
  }
}

/**
 * Clears every namespace cache and in-flight dedupe map. Useful on auth
 * identity changes so responses from the previous session are discarded.
 */
export function invalidateAll() {
  NAMESPACES.clear();
}

/**
 * Builds a stable string key from a query-params object so callers can avoid
 * hand-rolling key strings.
 */
export function buildCacheKey(params) {
  const scopedParams = {
    __scope: getSessionScopeKey(),
    ...(params && typeof params === "object" ? params : {}),
  };
  const entries = Object.entries(scopedParams)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : String(v)]);
  entries.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return entries.map(([k, v]) => `${k}=${v}`).join("&");
}
