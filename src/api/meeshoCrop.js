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
 * Meesho-only: runs Python PyMuPDF pipelines on the server.
 * @param {File[]} files
 * @param {string} sortBy  order_id | sku | delivery
 * @param {string} layout  label_printer | keep_invoice
 * @param {boolean} [printDateTime] stamp print date/time on each output page
 * @param {boolean} [multiOrderBottom] extend crop downward for multi-order footer
 * @param {string} [customMessage] optional text printed near Product Details
 * @returns {Promise<Uint8Array>}
 */
export async function fetchMeeshoCroppedPdf(
  files,
  sortBy,
  layout,
  printDateTime = false,
  multiOrderBottom = false,
  customMessage = "",
) {
  const form = new FormData();
  for (const f of files) {
    form.append("files", f);
  }
  form.append("sort_by", sortBy);
  form.append("layout", layout);
  form.append("print_datetime", printDateTime ? "1" : "0");
  form.append("multi_order_bottom", multiOrderBottom ? "1" : "0");
  form.append("custom_message", (customMessage || "").trim());

  const res = await fetch(apiPath("/api/crop/meesho"), {
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
