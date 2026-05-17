/** Shared helpers for durable async processing tasks. */
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
    // Fall back to raw response.
  }
  return text;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function _shouldRetry(status) {
  return status === 408 || status === 425 || status === 429 || status >= 500;
}

export async function fetchWithRetry(url, options = {}, { retries = 3, timeoutMs = 12000 } = {}) {
  let attempt = 0;
  let lastError = null;
  while (attempt <= retries) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, { ...options, signal: controller.signal });
      clearTimeout(timeout);
      if (res.ok) return res;
      if (attempt < retries && _shouldRetry(res.status)) {
        await sleep(Math.min(2500, 350 * Math.pow(2, attempt)));
        attempt += 1;
        continue;
      }
      throw new Error(await parseError(res));
    } catch (error) {
      clearTimeout(timeout);
      if (error && typeof error === "object" && error.name === "AbortError") {
        lastError = new Error(
          `Request timed out after ${Math.max(1, Math.round(timeoutMs / 1000))}s. Please retry.`,
        );
      } else {
        lastError = error instanceof Error ? error : new Error(String(error));
      }
      if (attempt >= retries) break;
      await sleep(Math.min(2500, 350 * Math.pow(2, attempt)));
      attempt += 1;
    }
  }
  throw lastError || new Error("Request failed");
}

export async function fetchTaskStatus(taskId) {
  const safeTaskId = String(taskId || "").trim();
  if (!safeTaskId) {
    throw new Error("Task id is required.");
  }
  const id = encodeURIComponent(safeTaskId);
  const res = await fetchWithRetry(
    apiPath(`/api/tasks/${id}`),
    {
      method: "GET",
      headers: authHeader(),
    },
    {
      // Polling can overlap with heavy server-side work and object-storage hops.
      // Use a wider timeout to reduce false "Temporary network issue" flicker.
      retries: 5,
      timeoutMs: 25000,
    },
  );
  const data = await res.json();
  const t = data.task || {};
  return {
    taskId: t.task_id || "",
    taskType: t.task_type || "",
    status: t.status || "queued",
    progress: Number.isFinite(t.progress) ? t.progress : 0,
    message: typeof t.message === "string" ? t.message : "",
    error: typeof t.error === "string" ? t.error : "",
    hasOutput: Boolean(t.has_output),
    summary: t.summary && typeof t.summary === "object" ? t.summary : {},
  };
}

/**
 * Download crop/OCR artifacts. Production uses R2 presigned URLs.
 *
 * Prefer `GET .../download?as_json=1` so the SPA receives the presigned URL in JSON.
 * That avoids CORS hiding `Location` on cross-origin 307 responses (which broke manual
 * redirect handling and surfaced confusing errors).
 *
 * The presigned URL is then fetched without Bearer auth. Large PDFs use a long timeout
 * only on that second hop (not on status polling).
 */
export async function downloadTaskArtifact(taskId) {
  const safeTaskId = String(taskId || "").trim();
  if (!safeTaskId) {
    throw new Error("Task id is required.");
  }
  const id = encodeURIComponent(safeTaskId);
  const baseDownload = apiPath(`/api/tasks/${id}/download`);
  const artifactTimeoutMs = Math.max(
    60000,
    Number.parseInt(String(import.meta.env.VITE_ARTIFACT_DOWNLOAD_TIMEOUT_MS || ""), 10) || 900000,
  );

  const readArtifactResponse = async (res) => {
    if (!res.ok) {
      throw new Error(await parseError(res));
    }
    const contentDisposition = res.headers.get("content-disposition") || "";
    const match = contentDisposition.match(/filename="?([^"]+)"?/i);
    const filename = match?.[1] || "";
    const contentType = res.headers.get("content-type") || "";
    const blob = await res.blob();
    return {
      bytes: await blob.arrayBuffer(),
      filename,
      contentType,
    };
  };

  const fetchWithArtifactTimeout = async (targetUrl, init = {}) => {
    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), artifactTimeoutMs);
    try {
      const res = await fetch(targetUrl, { ...init, signal: controller.signal });
      return res;
    } finally {
      clearTimeout(t);
    }
  };

  const sep = baseDownload.includes("?") ? "&" : "?";
  const metaUrl = `${baseDownload}${sep}as_json=1`;

  const metaRes = await fetchWithRetry(
    metaUrl,
    {
      method: "GET",
      headers: authHeader(),
    },
    {
      retries: 3,
      timeoutMs: 60000,
    },
  );

  const metaCt = metaRes.headers.get("content-type") || "";
  if (metaCt.includes("application/json")) {
    const data = await metaRes.json();
    const presigned = typeof data?.download_url === "string" ? data.download_url.trim() : "";
    const authenticatedRaw =
      typeof data?.authenticated_download_url === "string" ? data.authenticated_download_url.trim() : "";
    const authenticatedUrl = authenticatedRaw
      ? authenticatedRaw.startsWith("http://") || authenticatedRaw.startsWith("https://")
        ? authenticatedRaw
        : apiPath(authenticatedRaw)
      : `${baseDownload}${baseDownload.includes("?") ? "&" : "?"}proxy=1`;
    if (data?.use_authenticated_file_download || authenticatedRaw) {
      try {
        const fileRes = await fetchWithArtifactTimeout(authenticatedUrl, {
          method: "GET",
          headers: authHeader(),
        });
        return readArtifactResponse(fileRes);
      } catch (authErr) {
        if (!presigned) {
          throw authErr;
        }
      }
    }
    if (presigned) {
      const blobRes = await fetchWithArtifactTimeout(presigned, { method: "GET" });
      return readArtifactResponse(blobRes);
    }
    throw new Error("Download metadata missing presigned URL.");
  }

  // Older API (or fetch auto-followed 307): response body may already be the PDF/ZIP.
  if (
    metaRes.ok &&
    (metaCt.includes("pdf") ||
      metaCt.includes("zip") ||
      metaCt.includes("octet-stream") ||
      metaCt.includes("binary"))
  ) {
    return readArtifactResponse(metaRes);
  }

  // Older API without JSON mode: follow redirect manually if possible.
  const first = await fetchWithArtifactTimeout(baseDownload, {
    method: "GET",
    headers: authHeader(),
    redirect: "manual",
  });

  if ([301, 302, 303, 307, 308].includes(first.status)) {
    const loc = first.headers.get("Location");
    if (!loc) {
      throw new Error(
        "Download redirect missing Location header. Redeploy API with as_json=1 support or CORS expose_headers Location.",
      );
    }
    const second = await fetchWithArtifactTimeout(loc, { method: "GET" });
    return readArtifactResponse(second);
  }

  return readArtifactResponse(first);
}

export async function fetchTaskDownloadUrl(taskId) {
  const safeTaskId = String(taskId || "").trim();
  if (!safeTaskId) {
    throw new Error("Task id is required.");
  }
  const id = encodeURIComponent(safeTaskId);
  const baseDownload = apiPath(`/api/tasks/${id}/download`);
  const sep = baseDownload.includes("?") ? "&" : "?";
  const metaUrl = `${baseDownload}${sep}as_json=1`;
  const metaRes = await fetchWithRetry(
    metaUrl,
    {
      method: "GET",
      headers: authHeader(),
    },
    {
      retries: 2,
      timeoutMs: 30000,
    },
  );
  const metaCt = metaRes.headers.get("content-type") || "";
  if (metaCt.includes("application/json")) {
    const data = await metaRes.json();
    const presigned = typeof data?.download_url === "string" ? data.download_url.trim() : "";
    return presigned;
  }

  const first = await fetch(baseDownload, {
    method: "GET",
    headers: authHeader(),
    redirect: "manual",
  });
  if ([301, 302, 303, 307, 308].includes(first.status)) {
    return first.headers.get("Location") || "";
  }
  return "";
}

export async function startCropTask(platform, files, options = {}) {
  const cleanPlatform = String(platform || "").trim().toLowerCase();
  const endpoint =
    cleanPlatform === "meesho"
      ? "/api/crop/meesho/start"
      : cleanPlatform === "flipkart"
        ? "/api/crop/flipkart/start"
        : "";
  if (!endpoint) throw new Error(`Unsupported crop platform: ${platform}`);
  const form = new FormData();
  for (const f of files || []) form.append("files", f);
  if (typeof options.sortBy === "string" && options.sortBy) form.append("sort_by", options.sortBy);
  if (typeof options.layout === "string" && options.layout) form.append("layout", options.layout);
  if (typeof options.separatePincodes === "string" && options.separatePincodes.trim()) {
    form.append("separate_pincodes", options.separatePincodes.trim());
  }
  if (typeof options.detectSuspicious === "boolean") {
    form.append("detect_suspicious", options.detectSuspicious ? "1" : "0");
  }
  if (typeof options.markSuspiciousPreview === "boolean") {
    form.append("mark_suspicious_preview", options.markSuspiciousPreview ? "1" : "0");
  }
  if (cleanPlatform === "meesho") {
    form.append("print_datetime", options.printDateTime ? "1" : "0");
    form.append("multi_order_bottom", options.multiOrderBottom ? "1" : "0");
    form.append("custom_message", (options.customMessage || "").trim());
    form.append(
      "separate_multi_order_by_customer",
      options.separateMultiOrderByCustomer ? "1" : "0",
    );
    form.append("mark_loyal_customer", options.markLoyalCustomer ? "1" : "0");
    form.append("mark_loyal_customer_preview", options.markLoyalCustomerPreview ? "1" : "0");
  } else {
    form.append("print_datetime", options.printDateTime ? "1" : "0");
    form.append("multi_order_bottom", options.multiOrderBottom ? "1" : "0");
    form.append("custom_message", (options.customMessage || "").trim());
    form.append(
      "separate_multi_order_by_customer",
      options.separateMultiOrderByCustomer ? "1" : "0",
    );
    form.append("mark_loyal_customer", options.markLoyalCustomer ? "1" : "0");
    form.append("mark_loyal_customer_preview", options.markLoyalCustomerPreview ? "1" : "0");
  }
  const res = await fetchWithRetry(
    apiPath(endpoint),
    {
      method: "POST",
      headers: authHeader(),
      body: form,
    },
    {
      // Starting a crop uploads PDFs and can legitimately take much longer
      // than normal API reads on slower networks. Use a longer timeout and
      // avoid automatic retries to prevent duplicate task creation.
      retries: 0,
      timeoutMs: 300000,
    },
  );
  const data = await res.json();
  return {
    taskId: data.task_id || "",
    jobId: Number.isFinite(data.job_id) ? data.job_id : null,
    status: data.status || "queued",
    progress: Number.isFinite(data.progress) ? data.progress : 0,
  };
}

