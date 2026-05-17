import { fetchTaskStatus, fetchWithRetry } from "./taskApi.js";

/** Base URL for API in production. Empty = same origin / Vite dev proxy. */
function apiPath(path) {
  const base = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
  return base ? `${base}${path}` : path;
}

function authHeader() {
  try {
    const raw = localStorage.getItem("cropperhub_session");
    if (!raw) return {};
    const session = JSON.parse(raw);
    const token = typeof session?.token === "string" ? session.token : "";
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

function buildOcrParams({ columnPreset = "standard_v1", customColumns = "", maxWorkers = 0 } = {}) {
  const params = new URLSearchParams();
  if (columnPreset) params.set("column_preset", columnPreset);
  const trimmedCustom = (customColumns || "").trim();
  if (trimmedCustom) params.set("custom_columns", trimmedCustom);
  if (Number.isFinite(maxWorkers) && Number(maxWorkers) > 0) {
    params.set("max_workers", String(Math.min(16, Math.max(1, Number(maxWorkers)))));
  }
  return params.toString();
}

export async function startLabelOcrExcelTask(
  files,
  { columnPreset = "standard_v1", customColumns = "", maxWorkers = 0 } = {},
) {
  const formData = new FormData();
  for (const file of files) formData.append("files", file);
  const suffix = buildOcrParams({ columnPreset, customColumns, maxWorkers });
  const res = await fetchWithRetry(apiPath(`/api/ocr/labels/excel/start${suffix ? `?${suffix}` : ""}`), {
    method: "POST",
    headers: authHeader(),
    body: formData,
  });
  const data = await res.json();
  return {
    taskId: data.task_id || "",
    jobId: Number.isFinite(data.job_id) ? data.job_id : null,
    status: data.status || "queued",
    progress: Number.isFinite(data.progress) ? data.progress : 0,
  };
}

export async function fetchLabelOcrTaskStatus(taskId) {
  const t = await fetchTaskStatus(taskId);
  return {
    taskId: t.taskId || "",
    status: t.status || "queued",
    progress: Number.isFinite(t.progress) ? t.progress : 0,
    message: t.message || "",
    error: t.error || "",
    hasOutput: Boolean(t.hasOutput),
    summary: t.summary || {},
  };
}

export async function downloadLabelOcrTaskExcel() {
  throw new Error("OCR output is stored on server and cannot be downloaded.");
}
