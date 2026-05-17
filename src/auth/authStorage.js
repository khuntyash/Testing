const USERS_KEY = "cropperhub_users";
const SESSION_KEY = "cropperhub_session";

/** @returns {{ email: string, passwordHash: string, name: string }[]} */
export function getRegisteredUsers() {
  try {
    const raw = localStorage.getItem(USERS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** @param {{ email: string, passwordHash: string, name: string }[]} users */
function saveUsers(users) {
  localStorage.setItem(USERS_KEY, JSON.stringify(users));
}

export async function hashPassword(password) {
  const enc = new TextEncoder().encode(password);
  const buf = await crypto.subtle.digest("SHA-256", enc);
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * @param {{ name: string, email: string, password: string }} input
 * @throws {Error} duplicate email
 */
export async function registerUser({ name, email, password }) {
  const normalized = email.trim().toLowerCase();
  const users = getRegisteredUsers();
  if (users.some((u) => u.email === normalized)) {
    throw new Error("That email is already registered.");
  }
  const passwordHash = await hashPassword(password);
  users.push({
    email: normalized,
    passwordHash,
    name: name.trim() || normalized.split("@")[0],
  });
  saveUsers(users);
  return { email: normalized, name: name.trim() || normalized.split("@")[0] };
}

/**
 * @returns {Promise<{ email: string, name: string } | null>}
 */
export async function verifyCredentials(email, password) {
  const normalized = email.trim().toLowerCase();
  const users = getRegisteredUsers();
  const row = users.find((u) => u.email === normalized);
  if (!row) return null;
  const hash = await hashPassword(password);
  if (hash !== row.passwordHash) return null;
  return { email: row.email, name: row.name };
}

/** @param {{ email: string, name: string, token?: string, isAdmin?: boolean }} session */
export function saveSession(session) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

/** @returns {{ email: string, name: string, token?: string, isAdmin?: boolean } | null} */
export function loadSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const s = JSON.parse(raw);
    if (
      s &&
      typeof s.email === "string" &&
      typeof s.name === "string" &&
      (typeof s.token === "undefined" || typeof s.token === "string") &&
      (typeof s.isAdmin === "undefined" || typeof s.isAdmin === "boolean")
    ) {
      return s;
    }
    return null;
  } catch {
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

/**
 * Updates display name in the users table (if present) and refreshes the session.
 * @param {string} email
 * @param {{ name: string }} updates
 * @returns {{ email: string, name: string }}
 */
export function updateUserProfile(email, { name }) {
  const normalized = email.trim().toLowerCase();
  const trimmedName = (name || "").trim();
  const finalName = trimmedName || normalized.split("@")[0] || "User";
  const users = getRegisteredUsers();
  const i = users.findIndex((u) => u.email === normalized);
  if (i >= 0) {
    users[i] = { ...users[i], name: finalName };
    saveUsers(users);
  }
  const prev = loadSession();
  const session = {
    email: normalized,
    name: finalName,
    ...(typeof prev?.isAdmin === "boolean" ? { isAdmin: prev.isAdmin } : {}),
    ...(typeof prev?.token === "string" ? { token: prev.token } : {}),
  };
  saveSession(session);
  return session;
}
