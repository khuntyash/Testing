/** Base URL for API in production. Empty = same origin / Vite dev proxy. */
function apiPath(path) {
  const base = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  return base ? `${base}${path}` : path;
}

function authHeaders() {
  try {
    const raw = localStorage.getItem("cropperhub_session");
    if (!raw) return {};
    const session = JSON.parse(raw);
    if (typeof session?.token === "string" && session.token.trim()) {
      return { Authorization: `Bearer ${session.token}` };
    }
  } catch {
    // Ignore malformed session and send request without auth header.
  }
  return {};
}

/**
 * Flipkart backend crop pipeline.
 * @param {File[]} files
 * @param {string} layout label_printer | keep_invoice
 * @param {string} sortBy currently supports "sku"
 * @param {boolean} multiOrderBottom put multi-qty invoices at bottom
 * @returns {Promise<Uint8Array>}
 */
export async function fetchFlipkartCroppedPdf(files, layout, sortBy, multiOrderBottom) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  form.append("layout", layout);
  form.append("sort_by", sortBy || "sku");
  form.append("multi_order_bottom", multiOrderBottom ? "1" : "0");

  const res = await fetch(apiPath("/api/crop/flipkart"), {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(errText || `Server error (${res.status})`);
  }
  return new Uint8Array(await res.arrayBuffer());
}

