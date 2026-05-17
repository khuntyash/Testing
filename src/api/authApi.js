/** Base URL for API in production. Empty = same origin / Vite dev proxy. */
function apiPath(path) {
  const base = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  return base ? `${base}${path}` : path;
}

async function parseError(res) {
  const text = await res.text();
  if (!text) return `Request failed (${res.status})`;
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed?.detail === "string") return parsed.detail;
  } catch {
    // Ignore parse errors and fallback to raw text.
  }
  return text;
}

function toClientUser(user, token) {
  return {
    email: user?.email || "",
    name: user?.name || "User",
    isAdmin: Boolean(user?.is_admin),
    token,
  };
}

export async function apiSignup({ name, email, password }) {
  const res = await fetch(apiPath("/api/auth/signup"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return toClientUser(data.user, data.token);
}

export async function apiLogin({ email, password }) {
  const res = await fetch(apiPath("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return toClientUser(data.user, data.token);
}

export async function apiGetCurrentUser(token) {
  const res = await fetch(apiPath("/api/auth/me"), {
    method: "GET",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return toClientUser(data.user, token);
}

export async function apiLogout(token) {
  if (!token) return;
  const res = await fetch(apiPath("/api/auth/logout"), {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(await parseError(res));
}

export async function apiUpdateProfile(token, { name }) {
  const res = await fetch(apiPath("/api/auth/profile"), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return toClientUser(data.user, token);
}
