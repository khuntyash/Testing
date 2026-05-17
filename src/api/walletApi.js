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

function normalizeWallet(payload) {
  const txs = Array.isArray(payload?.transactions) ? payload.transactions : [];
  return {
    balance: Number(payload?.balance || 0),
    transactions: txs,
  };
}

export async function fetchWallet() {
  const res = await fetch(apiPath("/api/wallet"), {
    method: "GET",
    headers: authHeader(),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return normalizeWallet(data);
}

export async function spendWalletCoins({ amount, note }) {
  const res = await fetch(apiPath("/api/wallet/spend"), {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeader() },
    body: JSON.stringify({
      amount: Number(amount || 0),
      note: note || "",
    }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const data = await res.json();
  return {
    ok: Boolean(data?.ok),
    wallet: normalizeWallet(data?.wallet),
  };
}
