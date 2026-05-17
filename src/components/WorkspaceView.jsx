import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCropHistoryJobs, invalidateHistoryCache } from "../api/historyApi.js";
import { fetchLabelOcrTaskStatus, startLabelOcrExcelTask } from "../api/labelOcrApi.js";
import { startReturnAnalysisTask } from "../api/returnAnalysisApi.js";
import { downloadTaskArtifact, fetchTaskDownloadUrl, fetchTaskStatus, startCropTask } from "../api/taskApi.js";
import { useAuth } from "../auth/AuthContext.jsx";
import { OUTPUT_LAYOUTS, PLATFORMS, SORT_OPTIONS } from "../constants/platforms.js";
import { brand, font } from "../theme/brandTheme.js";
import { PREMIUM_CROP_COIN_COST_PER_LABEL } from "../wallet/coinConfig.js";
import { useWallet } from "../wallet/WalletContext.jsx";
import { mergePdfFiles } from "../utils/mergePdfs.js";
import CoinIcon from "./CoinIcon.jsx";
import FileItem from "./FileItem.jsx";
import { CheckIcon, UploadIcon } from "./icons.jsx";
import MeeshoNeonView from "./MeeshoNeonView.jsx";
import PlatformLogo from "./PlatformLogo.jsx";

const OCR_COLUMN_PRESETS = [
  { value: "standard_v1", label: "Standard v1 (reference)" },
  { value: "reference_v2", label: "Reference v2 (renamed columns)" },
  { value: "compact_v1", label: "Compact v1 (short format)" },
  { value: "custom", label: "Custom columns (comma-separated)" },
];
const OCR_PROGRESS_POLL_MS = 1500;
const TASK_POLL_MS = 1500;
const ACTIVE_TASKS_KEY = "cropperhub_active_tasks_v2";
const WORKSPACE_SNAPSHOTS_KEY = "cropperhub_workspace_snapshots_v2";
const SHARED_PINCODE_PREFS_KEY = "cropperhub_shared_pincode_prefs_v2";
const LEGACY_ACTIVE_TASKS_KEY = "cropperhub_active_tasks_v1";
const LEGACY_WORKSPACE_SNAPSHOTS_KEY = "cropperhub_workspace_snapshots_v1";
const LEGACY_SHARED_PINCODE_PREFS_KEY = "cropperhub_shared_pincode_prefs_v1";

const TASK_TERMINAL_STATUSES = new Set(["idle", "success", "failed", "cancelled", "expired"]);

function buildUserScopeKey(user) {
  const id =
    user?.id ??
    user?.userId ??
    user?.uid ??
    (typeof user?.email === "string" ? user.email.trim().toLowerCase() : "");
  const stable = String(id || "").trim().toLowerCase();
  return stable ? encodeURIComponent(stable) : "anonymous";
}

function scopedSessionKey(baseKey, userScopeKey) {
  return `${baseKey}::${String(userScopeKey || "anonymous")}`;
}

function dropLegacyWorkspaceStateOnce() {
  try {
    sessionStorage.removeItem(LEGACY_ACTIVE_TASKS_KEY);
    sessionStorage.removeItem(LEGACY_WORKSPACE_SNAPSHOTS_KEY);
    sessionStorage.removeItem(LEGACY_SHARED_PINCODE_PREFS_KEY);
  } catch {
    // Best-effort only.
  }
}

function loadActiveTasks(userScopeKey) {
  try {
    const raw = sessionStorage.getItem(scopedSessionKey(ACTIVE_TASKS_KEY, userScopeKey));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveActiveTask(userScopeKey, platformId, payload) {
  try {
    const state = loadActiveTasks(userScopeKey);
    if (payload) state[platformId] = payload;
    else delete state[platformId];
    sessionStorage.setItem(scopedSessionKey(ACTIVE_TASKS_KEY, userScopeKey), JSON.stringify(state));
  } catch {
    // Ignore storage failures in private mode.
  }
}

function loadWorkspaceSnapshots(userScopeKey) {
  try {
    const raw = sessionStorage.getItem(scopedSessionKey(WORKSPACE_SNAPSHOTS_KEY, userScopeKey));
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function saveWorkspaceSnapshot(userScopeKey, platformId, payload) {
  try {
    const state = loadWorkspaceSnapshots(userScopeKey);
    if (payload) state[platformId] = payload;
    else delete state[platformId];
    sessionStorage.setItem(
      scopedSessionKey(WORKSPACE_SNAPSHOTS_KEY, userScopeKey),
      JSON.stringify(state),
    );
  } catch {
    // Ignore storage failures in private mode.
  }
}

function loadSharedPincodePrefs(userScopeKey) {
  try {
    const raw = sessionStorage.getItem(scopedSessionKey(SHARED_PINCODE_PREFS_KEY, userScopeKey));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return {
      enabled: typeof parsed.enabled === "boolean" ? parsed.enabled : false,
      pincodes: String(parsed.pincodes || ""),
    };
  } catch {
    return null;
  }
}

function saveSharedPincodePrefs(userScopeKey, payload) {
  try {
    const scopedKey = scopedSessionKey(SHARED_PINCODE_PREFS_KEY, userScopeKey);
    if (!payload || typeof payload !== "object") {
      sessionStorage.removeItem(scopedKey);
      return;
    }
    sessionStorage.setItem(
      scopedKey,
      JSON.stringify({
        enabled: Boolean(payload.enabled),
        pincodes: String(payload.pincodes || ""),
      }),
    );
  } catch {
    // Ignore storage failures in private mode.
  }
}

function toQueuedFileMetadata(files) {
  if (!Array.isArray(files)) return [];
  return files
    .filter((file) => file && typeof file === "object")
    .map((file) => ({
      name: String(file.name || "document.pdf"),
      size: Number.isFinite(file.size) ? Number(file.size) : 0,
      lastModified: Number.isFinite(file.lastModified) ? Number(file.lastModified) : 0,
      type: String(file.type || "application/pdf"),
    }));
}

function fromQueuedFileMetadata(list) {
  if (!Array.isArray(list)) return [];
  return list
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      name: String(item.name || "document.pdf"),
      size: Number.isFinite(item.size) ? Number(item.size) : 0,
      lastModified: Number.isFinite(item.lastModified) ? Number(item.lastModified) : 0,
      type: String(item.type || "application/pdf"),
    }));
}

function isRealFileObject(file) {
  return typeof File !== "undefined" && file instanceof File;
}

function isTaskLikelyActive({ taskId, status, processing }) {
  if (processing) return true;
  if (!String(taskId || "").trim()) return false;
  const normalized = String(status || "idle").trim().toLowerCase();
  return !TASK_TERMINAL_STATUSES.has(normalized);
}

function normalizeCourierName(name) {
  const label = String(name || "Unknown").trim() || "Unknown";
  return /^xpress\s*bees?$/i.test(label) ? "Xpress Bees" : label;
}

function sanitizeFileNamePart(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^[-._]+|[-._]+$/g, "");
}

function formatPlatformNamePart(value) {
  return String(value || "")
    .trim()
    .replace(/[^a-zA-Z0-9]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function capitalizeFirst(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function toTitleCaseWords(value) {
  return String(value || "")
    .split(/[-_]+/)
    .filter(Boolean)
    .map((part) => capitalizeFirst(part.toLowerCase()))
    .join("-");
}

function buildPlatformDownloadName(platformName, rawFileName, fallbackExt = "pdf") {
  const safePlatform = formatPlatformNamePart(platformName) || "Platform";
  const sourceName = String(rawFileName || "").trim();
  const dotIndex = sourceName.lastIndexOf(".");
  const hasExtension = dotIndex > 0 && dotIndex < sourceName.length - 1;
  const rawBase = hasExtension ? sourceName.slice(0, dotIndex) : sourceName;
  const rawExt = hasExtension ? sourceName.slice(dotIndex + 1) : fallbackExt;
  const safeBase = sanitizeFileNamePart(rawBase) || "labels";
  const safeExt = sanitizeFileNamePart(rawExt) || fallbackExt;
  const now = new Date();
  const dd = String(now.getDate()).padStart(2, "0");
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const yyyy = String(now.getFullYear());
  const isCroppedBundle = /^cropped-labels(?:-risk-split)?$/i.test(rawBase.trim());
  const finalBase = isCroppedBundle ? "Cropped" : toTitleCaseWords(safeBase);
  return `${dd}-${mm}-${yyyy}_${safePlatform}_${finalBase}.${safeExt}`;
}

function resolveDownloadPlatformName(defaultPlatformName, platformHint, artifactFileName = "") {
  const hint = String(platformHint || "")
    .trim()
    .toLowerCase();
  if (hint === "flipkart") return "Flipkart";
  if (hint === "meesho") return "Meesho";
  const fileName = String(artifactFileName || "").toLowerCase();
  if (fileName.includes("flipkart")) return "Flipkart";
  if (fileName.includes("meesho")) return "Meesho";
  return String(defaultPlatformName || "Platform");
}

function buildCourierBreakdown(summary) {
  if (!summary || typeof summary !== "object") return null;
  const raw = summary.courier_counts;
  if (!raw || typeof raw !== "object") return null;
  const preferredOrder = ["ValmoPlus", "Valmo", "Delhivery", "Shadowfax", "Xpress Bees"];
  const preferredIndex = new Map(preferredOrder.map((name, idx) => [name.toLowerCase(), idx]));
  const entries = Object.entries(raw)
    .map(([name, value]) => [normalizeCourierName(name), Number(value) || 0])
    .filter(([, value]) => value > 0);
  if (!entries.length) return null;
  entries.sort((a, b) => {
    const aIdx = preferredIndex.get(String(a[0] || "").toLowerCase());
    const bIdx = preferredIndex.get(String(b[0] || "").toLowerCase());
    if (aIdx !== undefined && bIdx !== undefined) return aIdx - bIdx;
    if (aIdx !== undefined) return -1;
    if (bIdx !== undefined) return 1;
    if (a[0] === "Unknown" && b[0] !== "Unknown") return 1;
    if (b[0] === "Unknown" && a[0] !== "Unknown") return -1;
    if (b[1] !== a[1]) return b[1] - a[1];
    return a[0].localeCompare(b[0]);
  });
  const total =
    Number(summary.courier_count_total) || entries.reduce((acc, [, value]) => acc + value, 0);
  return { entries, total, error: String(summary.courier_count_error || "") };
}

function mergeCourierSummary(previousSummary, latestRunSummary) {
  if (!latestRunSummary || typeof latestRunSummary !== "object") {
    return previousSummary && typeof previousSummary === "object" ? previousSummary : null;
  }
  const prev = previousSummary && typeof previousSummary === "object" ? previousSummary : {};
  const next = latestRunSummary;
  const mergedCounts = {};

  const appendCounts = (raw) => {
    if (!raw || typeof raw !== "object") return;
    Object.entries(raw).forEach(([name, value]) => {
      const label = normalizeCourierName(name);
      const count = Number(value) || 0;
      if (count <= 0) return;
      mergedCounts[label] = (mergedCounts[label] || 0) + count;
    });
  };

  appendCounts(prev.courier_counts);
  appendCounts(next.courier_counts);

  const mergedTotal = Object.values(mergedCounts).reduce((acc, value) => acc + value, 0);
  return {
    ...prev,
    ...next,
    courier_counts: mergedCounts,
    courier_count_total: mergedTotal,
  };
}

function isPremiumCropOptionsEnabled(options) {
  if (!options || typeof options !== "object") return false;
  // Premium billing should apply only to premium risk/split features, not to
  // print/layout conveniences like date/time, message footer, or SKU grouping.
  const hasSeparatePincodes = Boolean(
    String(options.separate_pincodes || options.separatePincodes || "").trim(),
  );
  return Boolean(
    options.detect_suspicious ||
      options.detectSuspicious ||
      options.detect_suspicious_enabled ||
      options.mark_suspicious_preview ||
      options.markSuspiciousPreview ||
      options.suspicious_preview_enabled ||
      options.separate_multi_order_by_customer ||
      options.separateMultiOrderByCustomer ||
      options.multi_order_split_enabled ||
      options.mark_loyal_customer ||
      options.markLoyalCustomer ||
      options.loyal_customer_enabled ||
      options.mark_loyal_customer_preview ||
      options.markLoyalCustomerPreview ||
      options.loyal_preview_enabled ||
      options.pincode_split_enabled ||
      hasSeparatePincodes,
  );
}

function resolveBillableLabelCount(summary) {
  if (!summary || typeof summary !== "object") return 0;
  const candidates = [
    summary.total_output_labels,
    summary.total_labels,
    summary.total_input_pages,
    summary.courier_count_total,
  ];
  for (const value of candidates) {
    const n = Number(value);
    if (Number.isFinite(n) && n > 0) return Math.max(0, Math.floor(n));
  }
  return 0;
}

function CourierCountsPanel({ summary, platformId }) {
  const breakdown = buildCourierBreakdown(summary);
  if (!breakdown) return null;
  const { entries, total, error } = breakdown;
  const isFlipkart = platformId === "flipkart";
  const heading = isFlipkart ? "Total orders per seller" : "Total orders per courier partner";
  const helperText = isFlipkart
    ? "Flipkart labels are grouped by Sold By when available, with courier-partner fallback when seller details are missing."
    : "Use these counts to verify with the delivery personnel before handing over the parcels.";
  return (
    <div
      style={{
        marginBottom: 16,
        background: "rgba(15, 23, 42, 0.45)",
        border: "1px solid rgba(74, 222, 128, 0.25)",
        borderRadius: 12,
        padding: "14px 16px",
        fontFamily: font,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 14, fontWeight: 700, color: "#bbf7d0" }}>
          {heading}
        </span>
        <span style={{ fontSize: 12, color: "#86efac" }}>
          {total} label{total === 1 ? "" : "s"} counted
        </span>
      </div>
      <p
        style={{
          fontSize: 12,
          color: "#cbd5f5",
          marginBottom: 10,
          lineHeight: 1.5,
        }}
      >
        {helperText}
      </p>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "grid",
          gap: 6,
        }}
      >
        {entries.map(([name, value]) => (
          <li
            key={name}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              padding: "6px 10px",
              borderRadius: 8,
              background: "rgba(15, 118, 110, 0.18)",
              border: "1px solid rgba(74, 222, 128, 0.18)",
            }}
          >
            <span
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: name === "Unknown" ? "#fbbf24" : "#e0f2fe",
              }}
            >
              {name}
            </span>
            <span style={{ fontSize: 13, fontWeight: 700, color: "#bbf7d0" }}>{value}</span>
          </li>
        ))}
      </ul>
      {error ? (
        <p style={{ marginTop: 8, fontSize: 11, color: "#fca5a5" }}>
          Some pages could not be parsed: {error}
        </p>
      ) : null}
    </div>
  );
}

export default function WorkspaceView({ platform: p }) {
  const { user } = useAuth();
  const userScopeKey = useMemo(
    () => buildUserScopeKey(user),
    [user?.id, user?.userId, user?.uid, user?.email],
  );
  const userScopeRef = useRef(userScopeKey);
  const { canAfford, spendCoins, balance } = useWallet();
  const [coinGateError, setCoinGateError] = useState(false);
  const [drag, setDrag] = useState(false);
  const [files, setFiles] = useState([]);
  const [outputLayout, setOutputLayout] = useState("label_printer");
  const [sortBy, setSortBy] = useState("order_id");
  const [printDateTimeOnLabel, setPrintDateTimeOnLabel] = useState(() => p.id !== "flipkart");
  const [multiOrderAtBottom, setMultiOrderAtBottom] = useState(() => p.id !== "flipkart");
  const [separatePincodesEnabled, setSeparatePincodesEnabled] = useState(false);
  const [separatePincodes, setSeparatePincodes] = useState("");
  const [detectSuspiciousBuyerEnabled, setDetectSuspiciousBuyerEnabled] = useState(true);
  const [suspiciousMarkerPreviewEnabled, setSuspiciousMarkerPreviewEnabled] = useState(false);
  const [separateMultiOrderEnabled, setSeparateMultiOrderEnabled] = useState(false);
  const [loyalCustomerEnabled, setLoyalCustomerEnabled] = useState(false);
  const [loyalCustomerPreviewEnabled, setLoyalCustomerPreviewEnabled] = useState(false);
  const [userHistorySuborderId, setUserHistorySuborderId] = useState("");
  const [printCustomMessage, setPrintCustomMessage] = useState(false);
  const [customPrintMessage, setCustomPrintMessage] = useState("");
  const [processing, setProcessing] = useState(false);
  const [processed, setProcessed] = useState(false);
  const [progress, setProgress] = useState(0);
  const [cropTaskId, setCropTaskId] = useState("");
  const [cropTaskStatus, setCropTaskStatus] = useState("idle");
  const [cropProgressMessage, setCropProgressMessage] = useState("");
  const [lastMergedCropTaskId, setLastMergedCropTaskId] = useState("");
  /** Merged output (single PDF for one or many inputs). */
  const [outputPdfBytes, setOutputPdfBytes] = useState(null);
  const [outputArtifactName, setOutputArtifactName] = useState("cropped-labels.pdf");
  const [outputArtifactMime, setOutputArtifactMime] = useState("application/pdf");
  const [outputPlatformName, setOutputPlatformName] = useState(String(p.name || "Platform"));
  const [cropBillingMessage, setCropBillingMessage] = useState("");
  const [cropTaskSummary, setCropTaskSummary] = useState(null);
  const [mergeError, setMergeError] = useState(null);
  const [ocrProcessing, setOcrProcessing] = useState(false);
  const [ocrError, setOcrError] = useState(null);
  const [ocrTaskId, setOcrTaskId] = useState("");
  const [ocrTaskStatus, setOcrTaskStatus] = useState("idle");
  const [ocrProgress, setOcrProgress] = useState(0);
  const [ocrProgressMessage, setOcrProgressMessage] = useState("");
  const [returnAnalysisProcessing, setReturnAnalysisProcessing] = useState(false);
  const [returnAnalysisError, setReturnAnalysisError] = useState(null);
  const [returnAnalysisTaskId, setReturnAnalysisTaskId] = useState("");
  const [returnAnalysisTaskStatus, setReturnAnalysisTaskStatus] = useState("idle");
  const [returnAnalysisProgress, setReturnAnalysisProgress] = useState(0);
  const [returnAnalysisProgressMessage, setReturnAnalysisProgressMessage] = useState("");
  const [returnAnalysisSummary, setReturnAnalysisSummary] = useState(null);
  const [ocrAutoStartedForCurrentFiles, setOcrAutoStartedForCurrentFiles] = useState(false);
  const [ocrColumnPreset, setOcrColumnPreset] = useState("standard_v1");
  const [ocrCustomColumns, setOcrCustomColumns] = useState("");
  const [ocrMaxWorkers, setOcrMaxWorkers] = useState(0);
  const cropPollErrorsRef = useRef(0);
  const ocrPollErrorsRef = useRef(0);
  const returnPollErrorsRef = useRef(0);
  const cropCoinChargedRef = useRef(false);
  const ocrWorkerRestartRetryRef = useRef(false);
  const handleGenerateOcrExcelRef = useRef(null);
  const inputRef = useRef(null);
  const returnInputRef = useRef(null);
  const [cropHistory, setCropHistory] = useState([]);
  const [historyDownloadJobId, setHistoryDownloadJobId] = useState("");
  const [filesRequireReselection, setFilesRequireReselection] = useState(false);
  const [restoreWarning, setRestoreWarning] = useState("");
  const [workspaceHydrated, setWorkspaceHydrated] = useState(false);
  const hasFiles = files.length > 0;
  const hasRealFiles = useMemo(() => files.some((file) => isRealFileObject(file)), [files]);

  useEffect(() => {
    userScopeRef.current = userScopeKey;
  }, [userScopeKey]);

  useEffect(() => {
    dropLegacyWorkspaceStateOnce();
  }, []);

  useEffect(() => {
    setWorkspaceHydrated(false);
    const defaultsEnabled = p.id !== "flipkart";
    const state = loadWorkspaceSnapshots(userScopeKey);
    const snapshot = state[p.id];
    const sharedPincodePrefs = loadSharedPincodePrefs(userScopeKey);
    const queuedFiles = fromQueuedFileMetadata(snapshot?.queuedFiles);
    const cropTaskIdNext = String(snapshot?.cropTaskId || "");
    const cropTaskStatusNext = String(snapshot?.cropTaskStatus || "idle");
    const ocrTaskIdNext = String(snapshot?.ocrTaskId || "");
    const ocrTaskStatusNext = String(snapshot?.ocrTaskStatus || "idle");
    const returnTaskIdNext = String(snapshot?.returnAnalysisTaskId || "");
    const returnTaskStatusNext = String(snapshot?.returnAnalysisTaskStatus || "idle");
    const hasResumableTask =
      isTaskLikelyActive({
        taskId: cropTaskIdNext,
        status: cropTaskStatusNext,
        processing: Boolean(snapshot?.processing),
      }) ||
      isTaskLikelyActive({
        taskId: ocrTaskIdNext,
        status: ocrTaskStatusNext,
        processing: Boolean(snapshot?.ocrProcessing),
      }) ||
      isTaskLikelyActive({
        taskId: returnTaskIdNext,
        status: returnTaskStatusNext,
        processing: Boolean(snapshot?.returnAnalysisProcessing),
      });
    const shouldWarnReselect = queuedFiles.length > 0 && !hasResumableTask;

    // Keep platform workspaces isolated while restoring each platform's own
    // saved UI state after route switches or page refresh.
    // Exception: pincode split input is intentionally shared across platforms.
    setFiles(queuedFiles);
    setOutputLayout(String(snapshot?.outputLayout || "label_printer"));
    setSortBy(String(snapshot?.sortBy || "order_id"));
    setPrintDateTimeOnLabel(
      typeof snapshot?.printDateTimeOnLabel === "boolean"
        ? snapshot.printDateTimeOnLabel
        : defaultsEnabled,
    );
    setMultiOrderAtBottom(
      typeof snapshot?.multiOrderAtBottom === "boolean"
        ? snapshot.multiOrderAtBottom
        : defaultsEnabled,
    );
    setSeparatePincodesEnabled(
      sharedPincodePrefs?.enabled ?? Boolean(snapshot?.separatePincodesEnabled),
    );
    setSeparatePincodes(sharedPincodePrefs?.pincodes ?? String(snapshot?.separatePincodes || ""));
    setDetectSuspiciousBuyerEnabled(
      typeof snapshot?.detectSuspiciousBuyerEnabled === "boolean"
        ? snapshot.detectSuspiciousBuyerEnabled
        : true,
    );
    setSuspiciousMarkerPreviewEnabled(Boolean(snapshot?.suspiciousMarkerPreviewEnabled));
    setSeparateMultiOrderEnabled(Boolean(snapshot?.separateMultiOrderEnabled));
    setLoyalCustomerEnabled(Boolean(snapshot?.loyalCustomerEnabled));
    setLoyalCustomerPreviewEnabled(Boolean(snapshot?.loyalCustomerPreviewEnabled));
    setUserHistorySuborderId(String(snapshot?.userHistorySuborderId || ""));
    setPrintCustomMessage(Boolean(snapshot?.printCustomMessage));
    setCustomPrintMessage(String(snapshot?.customPrintMessage || ""));
    setProcessing(Boolean(snapshot?.processing));
    setProcessed(Boolean(snapshot?.processed));
    setProgress(Number.isFinite(snapshot?.progress) ? Number(snapshot.progress) : 0);
    setCropTaskId(cropTaskIdNext);
    setCropTaskStatus(cropTaskStatusNext);
    setCropProgressMessage(String(snapshot?.cropProgressMessage || ""));
    setLastMergedCropTaskId(String(snapshot?.lastMergedCropTaskId || ""));
    setOutputPdfBytes(null);
    setOutputArtifactName(String(snapshot?.outputArtifactName || "cropped-labels.pdf"));
    setOutputArtifactMime(String(snapshot?.outputArtifactMime || "application/pdf"));
    setOutputPlatformName(String(snapshot?.outputPlatformName || p.name || "Platform"));
    setCropBillingMessage(String(snapshot?.cropBillingMessage || ""));
    setCropTaskSummary(
      snapshot?.cropTaskSummary && typeof snapshot.cropTaskSummary === "object"
        ? snapshot.cropTaskSummary
        : null,
    );
    setMergeError(snapshot?.mergeError ? String(snapshot.mergeError) : null);
    setOcrProcessing(Boolean(snapshot?.ocrProcessing));
    setOcrError(snapshot?.ocrError ? String(snapshot.ocrError) : null);
    setOcrTaskId(ocrTaskIdNext);
    setOcrTaskStatus(ocrTaskStatusNext);
    setOcrProgress(Number.isFinite(snapshot?.ocrProgress) ? Number(snapshot.ocrProgress) : 0);
    setOcrProgressMessage(String(snapshot?.ocrProgressMessage || ""));
    setReturnAnalysisProcessing(Boolean(snapshot?.returnAnalysisProcessing));
    setReturnAnalysisError(
      snapshot?.returnAnalysisError ? String(snapshot.returnAnalysisError) : null,
    );
    setReturnAnalysisTaskId(returnTaskIdNext);
    setReturnAnalysisTaskStatus(returnTaskStatusNext);
    setReturnAnalysisProgress(
      Number.isFinite(snapshot?.returnAnalysisProgress) ? Number(snapshot.returnAnalysisProgress) : 0,
    );
    setReturnAnalysisProgressMessage(String(snapshot?.returnAnalysisProgressMessage || ""));
    setReturnAnalysisSummary(
      snapshot?.returnAnalysisSummary && typeof snapshot.returnAnalysisSummary === "object"
        ? snapshot.returnAnalysisSummary
        : null,
    );
    setOcrAutoStartedForCurrentFiles(Boolean(snapshot?.ocrAutoStartedForCurrentFiles));
    setOcrColumnPreset(String(snapshot?.ocrColumnPreset || "standard_v1"));
    setOcrCustomColumns(String(snapshot?.ocrCustomColumns || ""));
    setOcrMaxWorkers(Number.isFinite(snapshot?.ocrMaxWorkers) ? Number(snapshot.ocrMaxWorkers) : 0);
    setCoinGateError(Boolean(snapshot?.coinGateError));
    setFilesRequireReselection(shouldWarnReselect);
    setRestoreWarning("");
    setWorkspaceHydrated(true);
  }, [p.id, userScopeKey]);

  useEffect(() => {
    if (!workspaceHydrated) return;
    saveSharedPincodePrefs(userScopeKey, {
      enabled: separatePincodesEnabled,
      pincodes: separatePincodes,
    });
  }, [workspaceHydrated, userScopeKey, separatePincodesEnabled, separatePincodes]);

  const refreshHistory = useCallback(
    async ({ bypassCache = false } = {}) => {
      if (p.id !== "meesho" && p.id !== "flipkart") {
        setCropHistory([]);
        return;
      }
      try {
        const { jobs } = await fetchCropHistoryJobs({
          platformId: p.id,
          limit: 60,
          offset: 0,
          bypassCache,
        });
        setCropHistory(jobs);
      } catch {
        // Avoid disrupting crop flow if history load fails.
        setCropHistory([]);
      }
    },
    [p.id, userScopeKey],
  );

  useEffect(() => {
    refreshHistory();
  }, [refreshHistory]);

  useEffect(() => {
    const state = loadActiveTasks(userScopeKey);
    const active = state[p.id];
    if (!active || typeof active !== "object") return;
    if (active.kind === "crop" && active.taskId) {
      setCropTaskId(String(active.taskId));
      setCropTaskStatus("queued");
      setProcessing(true);
      setProcessed(false);
      setProgress(1);
      setCropProgressMessage("Continuing process...");
    }
    if (active.kind === "ocr" && active.taskId) {
      setOcrTaskId(String(active.taskId));
      setOcrTaskStatus("queued");
      setOcrProcessing(true);
      setOcrProgress(1);
      setOcrProgressMessage("Continuing OCR process...");
    }
    if (active.kind === "return_analysis" && active.taskId) {
      setReturnAnalysisTaskId(String(active.taskId));
      setReturnAnalysisTaskStatus("queued");
      setReturnAnalysisProcessing(true);
      setReturnAnalysisProgress(1);
      setReturnAnalysisProgressMessage("Continuing return analysis...");
    }
  }, [p.id, userScopeKey]);

  const addFiles = useCallback(
    (raw) => {
      const pdfs = Array.from(raw).filter(
        (f) => f.type === "application/pdf" || f.name.endsWith(".pdf"),
      );
      if (pdfs.length) {
        // Start every new selection from a clean queue so counts/results are
        // calculated only for the newly selected batch.
        setFiles(pdfs);
        setFilesRequireReselection(false);
        setRestoreWarning("");
        setProcessed(false);
        setOutputPdfBytes(null);
        setOutputArtifactName("cropped-labels.pdf");
        setOutputArtifactMime("application/pdf");
        setCropBillingMessage("");
        setMergeError(null);
        setCropTaskId("");
        setCropTaskStatus("idle");
        setCropProgressMessage("");
        setOcrError(null);
        setOcrTaskId("");
        setOcrTaskStatus("idle");
        setOcrProgress(0);
        setOcrProgressMessage("");
        setReturnAnalysisError(null);
        setReturnAnalysisTaskId("");
        setReturnAnalysisTaskStatus("idle");
        setReturnAnalysisProgress(0);
        setReturnAnalysisProgressMessage("");
        setReturnAnalysisSummary(null);
        setOcrAutoStartedForCurrentFiles(false);
        saveActiveTask(userScopeKey, p.id, null);
        setCoinGateError(false);
        ocrWorkerRestartRetryRef.current = false;
      }
    },
    [p.id, userScopeKey],
  );

  const handleDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDrag(false);
      addFiles(e.dataTransfer.files);
    },
    [addFiles],
  );

  const handleProcess = useCallback(async () => {
    if (!files.length || processing) return;
    if (!hasRealFiles) {
      if (inputRef.current) inputRef.current.click();
      return;
    }
    setMergeError(null);
    setCoinGateError(false);

    const cropOptions = {
      sortBy,
      layout: outputLayout,
      printDateTime: printDateTimeOnLabel,
      multiOrderBottom: multiOrderAtBottom,
      customMessage: printCustomMessage ? customPrintMessage : "",
      separatePincodes: separatePincodesEnabled ? separatePincodes : "",
      detectSuspicious: detectSuspiciousBuyerEnabled,
      markSuspiciousPreview: suspiciousMarkerPreviewEnabled,
      separateMultiOrderByCustomer: separateMultiOrderEnabled,
      markLoyalCustomer: loyalCustomerEnabled,
      markLoyalCustomerPreview: loyalCustomerPreviewEnabled,
    };
    const hasPremiumFeaturesEnabled = isPremiumCropOptionsEnabled(cropOptions);
    if (
      (p.id === "meesho" || p.id === "flipkart") &&
      hasPremiumFeaturesEnabled &&
      !canAfford(PREMIUM_CROP_COIN_COST_PER_LABEL)
    ) {
      setCoinGateError(true);
      return;
    }

    const snapshot = [...files];
    setOutputPdfBytes(null);
    setOutputArtifactName("cropped-labels.pdf");
    setOutputArtifactMime("application/pdf");
    setCropBillingMessage("");
    setProcessed(false);
    setProcessing(true);
    setProgress(1);
    setCropTaskStatus("queued");
    setCropProgressMessage("Queued");
    cropPollErrorsRef.current = 0;
    cropCoinChargedRef.current = false;

    try {
      let bytes;
      if (p.id === "meesho") {
        const task = await startCropTask("meesho", snapshot, cropOptions);
        setCropTaskId(task.taskId || "");
        setCropTaskStatus(task.status || "queued");
        setCropProgressMessage(task.status === "queued" ? "Queued" : "Running");
        setProgress(Number.isFinite(task.progress) ? task.progress : 1);
        saveActiveTask(userScopeKey, p.id, { kind: "crop", taskId: task.taskId || "" });
        return;
      } else if (p.id === "flipkart") {
        const task = await startCropTask("flipkart", snapshot, cropOptions);
        setCropTaskId(task.taskId || "");
        setCropTaskStatus(task.status || "queued");
        setCropProgressMessage(task.status === "queued" ? "Queued" : "Running");
        setProgress(Number.isFinite(task.progress) ? task.progress : 1);
        saveActiveTask(userScopeKey, p.id, { kind: "crop", taskId: task.taskId || "" });
        return;
      } else {
        bytes = await mergePdfFiles(snapshot);
      }
      setOutputPdfBytes(bytes);
      setOutputArtifactName(`${p.name.replace(/\s+/g, "-")}-labels.pdf`);
      setOutputArtifactMime("application/pdf");
      setOutputPlatformName(String(p.name || "Platform"));
      setProcessed(true);
      setProgress(100);
    } catch (e) {
      setMergeError(e instanceof Error ? e.message : String(e));
      setCropTaskStatus("failed");
      setCropProgressMessage("Failed");
      setProcessing(false);
    } finally {
      if (p.id !== "meesho" && p.id !== "flipkart") {
        setProcessing(false);
      }
    }
  }, [
    files,
    hasRealFiles,
    processing,
    p.id,
    canAfford,
    sortBy,
    outputLayout,
    printDateTimeOnLabel,
    multiOrderAtBottom,
    separatePincodesEnabled,
    separatePincodes,
    detectSuspiciousBuyerEnabled,
    suspiciousMarkerPreviewEnabled,
    separateMultiOrderEnabled,
    loyalCustomerEnabled,
    loyalCustomerPreviewEnabled,
    printCustomMessage,
    customPrintMessage,
    userScopeKey,
  ]);

  const handleDownloadPdf = useCallback(async () => {
    if (outputPdfBytes) {
      const blob = new Blob([outputPdfBytes], { type: outputArtifactMime || "application/pdf" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const slug = p.name.replace(/\s+/g, "-");
      const fallbackName = files.length > 1 ? `${slug}-merged-labels.pdf` : `${slug}-labels.pdf`;
      a.download = buildPlatformDownloadName(
        outputPlatformName || p.name,
        outputArtifactName || fallbackName,
        "pdf",
      );
      a.click();
      URL.revokeObjectURL(url);
      return;
    }
    if (!cropTaskId) {
      setMergeError("Download is not ready yet. Please try from Recent Jobs.");
      return;
    }
    try {
      const artifact = await downloadTaskArtifact(cropTaskId);
      const blob = new Blob([artifact.bytes], {
        type: artifact.contentType || outputArtifactMime || "application/pdf",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const slug = p.name.replace(/\s+/g, "-");
      const fallbackName = files.length > 1 ? `${slug}-merged-labels.pdf` : `${slug}-labels.pdf`;
      a.download = buildPlatformDownloadName(
        outputPlatformName || p.name,
        artifact.filename || outputArtifactName || fallbackName,
        "pdf",
      );
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      try {
        const directUrl = await fetchTaskDownloadUrl(cropTaskId);
        if (directUrl) {
          window.location.assign(directUrl);
          return;
        }
      } catch {
        // Keep original error when fallback URL lookup also fails.
      }
      setMergeError(
        e instanceof Error
          ? `Download failed. ${e.message}`
          : "Download failed.",
      );
    }
  }, [
    cropTaskId,
    files.length,
    outputArtifactMime,
    outputArtifactName,
    outputPdfBytes,
    outputPlatformName,
    p.name,
    setMergeError,
  ]);

  const handleDownloadHistoryJob = useCallback(
    async (job) => {
      const jobId = String(job?.id || "");
      const taskId = String(job?.task_id || "");
      if (!jobId || !taskId) {
        setMergeError("This history entry does not have a downloadable artifact.");
        return;
      }
      setHistoryDownloadJobId(jobId);
      try {
        const artifact = await downloadTaskArtifact(taskId);
        const blob = new Blob([artifact.bytes], {
          type: artifact.contentType || "application/pdf",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        const fallbackName = artifact.contentType?.includes("zip")
          ? `crop-job-${jobId}.zip`
          : `crop-job-${jobId}.pdf`;
        const defaultExt = artifact.contentType?.includes("zip") ? "zip" : "pdf";
        const resolvedPlatform = resolveDownloadPlatformName(
          p.name,
          job?.platform,
          artifact.filename || fallbackName,
        );
        a.download = buildPlatformDownloadName(resolvedPlatform, artifact.filename || fallbackName, defaultExt);
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        try {
          const directUrl = await fetchTaskDownloadUrl(taskId);
          if (directUrl) {
            window.location.assign(directUrl);
            return;
          }
        } catch {
          // Keep original error when fallback URL lookup also fails.
        }
        setMergeError(e instanceof Error ? e.message : String(e));
      } finally {
        setHistoryDownloadJobId("");
      }
    },
    [setMergeError],
  );

  useEffect(() => {
    if (!cropTaskId) return;
    if (cropTaskStatus === "success" && processed) return;
    let cancelled = false;
    const effectUserScope = userScopeKey;
    const poll = async () => {
      if (cancelled || userScopeRef.current !== effectUserScope) return;
      try {
        const task = await fetchTaskStatus(cropTaskId);
        if (cancelled || userScopeRef.current !== effectUserScope) return;
        const taskStatus = task.status || "running";
        setProgress(Number.isFinite(task.progress) ? task.progress : 0);
        setCropProgressMessage(task.message || "");
        cropPollErrorsRef.current = 0;
        if (taskStatus === "success") {
          setCropTaskStatus("success");
          setProcessing(false);
          setProgress(100);
          setMergeError(null);
          saveActiveTask(userScopeKey, p.id, null);
          let artifactLoaded = false;
          try {
            const artifact = await downloadTaskArtifact(cropTaskId);
            if (cancelled || userScopeRef.current !== effectUserScope) return;
            setOutputPdfBytes(artifact.bytes);
            setOutputArtifactName(artifact.filename || "cropped-labels.pdf");
            setOutputArtifactMime(artifact.contentType || "application/pdf");
            setOutputPlatformName(
              resolveDownloadPlatformName(p.name, p.id, artifact.filename || "cropped-labels.pdf"),
            );
            artifactLoaded = true;
          } catch (artifactError) {
            // Keep success state when processing is complete; only auto-download failed.
            setCropProgressMessage(
              artifactError instanceof Error
                ? `Done. Auto-download failed; use Download in Recent Jobs. (${artifactError.message})`
                : "Done. Auto-download failed; use Download in Recent Jobs.",
            );
          }
          if (lastMergedCropTaskId !== cropTaskId) {
            setCropTaskSummary((previous) => mergeCourierSummary(previous, task.summary));
            setLastMergedCropTaskId(cropTaskId);
          }
          setProcessed(true);
          if ((p.id === "meesho" || p.id === "flipkart") && !cropCoinChargedRef.current) {
            cropCoinChargedRef.current = true;
            const summary = task.summary && typeof task.summary === "object" ? task.summary : {};
            const premiumEnabled =
              isPremiumCropOptionsEnabled(summary) ||
              isPremiumCropOptionsEnabled({
                printDateTime: printDateTimeOnLabel,
                multiOrderBottom: multiOrderAtBottom,
                customMessage: printCustomMessage ? customPrintMessage : "",
                separatePincodes: separatePincodesEnabled ? separatePincodes : "",
                detectSuspicious: detectSuspiciousBuyerEnabled,
                markSuspiciousPreview: suspiciousMarkerPreviewEnabled,
                separateMultiOrderByCustomer: separateMultiOrderEnabled,
                markLoyalCustomer: loyalCustomerEnabled,
                markLoyalCustomerPreview: loyalCustomerPreviewEnabled,
              });
            const labelCount = resolveBillableLabelCount(summary);
            const coinsToCharge = premiumEnabled
              ? labelCount * PREMIUM_CROP_COIN_COST_PER_LABEL
              : 0;
            if (coinsToCharge > 0) {
              const spent = await spendCoins(
                coinsToCharge,
                `${String(p.name || "Crop")} premium crop (${labelCount} label${labelCount === 1 ? "" : "s"})`,
              );
              if (!spent.ok) {
                setCoinGateError(true);
                setMergeError(
                  `PDF was built but ${coinsToCharge} coin${coinsToCharge === 1 ? "" : "s"} could not be deducted.`,
                );
                setCropBillingMessage(
                  `Premium billing pending: ${labelCount} label${labelCount === 1 ? "" : "s"} = ${coinsToCharge} coin${coinsToCharge === 1 ? "" : "s"} (deduction failed).`,
                );
              } else {
                setCropBillingMessage(
                  `Premium billing applied: ${coinsToCharge} Coin${coinsToCharge === 1 ? "" : "s"} used.`,
                );
              }
            } else if (premiumEnabled) {
              setCropBillingMessage("Premium options were enabled, but no billable labels were found. 0 coins charged.");
            } else {
              setCropBillingMessage("No premium options used. 0 coins charged.");
            }
          } else if (p.id === "meesho" || p.id === "flipkart") {
            setCropBillingMessage("No premium options used. 0 coins charged.");
          }
          invalidateHistoryCache();
          refreshHistory({ bypassCache: true });
          return;
        }
        if (taskStatus === "failed" || taskStatus === "cancelled" || taskStatus === "expired") {
          setCropTaskStatus(taskStatus);
          setProcessing(false);
          setMergeError(task.error || "Crop task failed.");
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
        setCropTaskStatus(taskStatus);
      } catch (e) {
        if (cancelled || userScopeRef.current !== effectUserScope) return;
        cropPollErrorsRef.current += 1;
        if (cropPollErrorsRef.current >= 8) {
          setProcessing(false);
          setCropTaskStatus("failed");
          setMergeError(e instanceof Error ? e.message : String(e));
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
        setCropProgressMessage("Temporary network issue. Retrying...");
      }
      if (!cancelled) {
        setTimeout(poll, TASK_POLL_MS);
      }
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [
    cropTaskId,
    cropTaskStatus,
    customPrintMessage,
    detectSuspiciousBuyerEnabled,
    lastMergedCropTaskId,
    loyalCustomerEnabled,
    loyalCustomerPreviewEnabled,
    multiOrderAtBottom,
    p.id,
    p.name,
    printCustomMessage,
    printDateTimeOnLabel,
    processed,
    refreshHistory,
    separateMultiOrderEnabled,
    separatePincodes,
    separatePincodesEnabled,
    spendCoins,
    suspiciousMarkerPreviewEnabled,
    userScopeKey,
  ]);

  const handleGenerateOcrExcel = useCallback(async (retrying = false) => {
    if (!files.length || ocrProcessing || processing) return;
    if (!hasRealFiles) {
      if (inputRef.current) inputRef.current.click();
      return;
    }
    if (!retrying) {
      ocrWorkerRestartRetryRef.current = false;
    }
    setOcrError(null);
    setOcrProcessing(true);
    setOcrTaskStatus("queued");
    setOcrProgress(1);
    setOcrProgressMessage("Queued");
    ocrPollErrorsRef.current = 0;
    try {
      const snapshot = [...files];
      const task = await startLabelOcrExcelTask(snapshot, {
        columnPreset: ocrColumnPreset,
        customColumns: ocrColumnPreset === "custom" ? ocrCustomColumns : "",
        maxWorkers: ocrMaxWorkers,
      });
      setOcrTaskId(task.taskId || "");
      setOcrTaskStatus(task.status || "queued");
      setOcrProgress(Number.isFinite(task.progress) ? task.progress : 1);
      setOcrProgressMessage(task.status === "queued" ? "Queued" : "Running");
      saveActiveTask(userScopeKey, p.id, { kind: "ocr", taskId: task.taskId || "" });
    } catch (e) {
      setOcrError(e instanceof Error ? e.message : String(e));
      setOcrTaskStatus("failed");
      setOcrProgress(100);
      setOcrProgressMessage("Failed");
      setOcrTaskId("");
      setOcrProcessing(false);
    } finally {
      // Progress polling effect controls final loading state.
    }
  }, [
    files,
    hasRealFiles,
    ocrColumnPreset,
    ocrCustomColumns,
    ocrMaxWorkers,
    ocrProcessing,
    processing,
    p.id,
    userScopeKey,
  ]);

  useEffect(() => {
    handleGenerateOcrExcelRef.current = handleGenerateOcrExcel;
  }, [handleGenerateOcrExcel]);

  useEffect(() => {
    if (!files.length) return;
    if (!hasRealFiles || filesRequireReselection) return;
    if (ocrAutoStartedForCurrentFiles) return;
    if (ocrProcessing || processing) return;
    if (ocrTaskId) return;
    setOcrAutoStartedForCurrentFiles(true);
    handleGenerateOcrExcel();
  }, [
    files,
    filesRequireReselection,
    handleGenerateOcrExcel,
    hasRealFiles,
    ocrAutoStartedForCurrentFiles,
    ocrProcessing,
    processing,
    ocrTaskId,
  ]);

  useEffect(() => {
    if (!ocrTaskId) return;
    if (ocrTaskStatus === "success" || ocrTaskStatus === "failed") {
      setOcrProcessing(false);
      return;
    }

    let cancelled = false;
    const effectUserScope = userScopeKey;
    const poll = async () => {
      if (cancelled || userScopeRef.current !== effectUserScope) return;
      try {
        const task = await fetchLabelOcrTaskStatus(ocrTaskId);
        if (cancelled || userScopeRef.current !== effectUserScope) return;
        setOcrTaskStatus(task.status || "processing");
        setOcrProgress(Number.isFinite(task.progress) ? task.progress : 0);
        setOcrProgressMessage(task.message || "");
        if (task.status === "success") {
          setOcrProcessing(false);
          setOcrProgressMessage("Completed. CSV stored securely on server.");
          invalidateHistoryCache();
          refreshHistory({ bypassCache: true });
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
        if (task.status === "failed" || task.status === "cancelled" || task.status === "expired") {
          const taskError = String(task.error || "OCR task failed.");
          const shouldAutoRetry =
            /worker restarted while processing/i.test(taskError) &&
            !ocrWorkerRestartRetryRef.current &&
            files.length > 0 &&
            hasRealFiles;
          if (shouldAutoRetry) {
            ocrWorkerRestartRetryRef.current = true;
            setOcrProcessing(false);
            setOcrError(null);
            setOcrTaskId("");
            setOcrTaskStatus("queued");
            setOcrProgress(1);
            setOcrProgressMessage("Worker restarted. Retrying OCR automatically...");
            saveActiveTask(userScopeKey, p.id, null);
            if (!cancelled) {
              setTimeout(() => {
                if (!cancelled) handleGenerateOcrExcelRef.current?.(true);
              }, 220);
            }
            return;
          }
          setOcrProcessing(false);
          setOcrError(taskError);
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
      } catch (e) {
        if (cancelled || userScopeRef.current !== effectUserScope) return;
        ocrPollErrorsRef.current += 1;
        if (ocrPollErrorsRef.current >= 8) {
          setOcrProcessing(false);
          setOcrTaskStatus("failed");
          setOcrError(e instanceof Error ? e.message : String(e));
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
        setOcrProgressMessage("Temporary network issue. Retrying...");
      }
      if (!cancelled) {
        setTimeout(poll, OCR_PROGRESS_POLL_MS);
      }
    };

    poll();
    return () => {
      cancelled = true;
    };
  }, [ocrTaskId, ocrTaskStatus, refreshHistory, p.id, files, hasRealFiles, handleGenerateOcrExcel, userScopeKey]);

  const handleStartReturnAnalysis = useCallback(
    async (file) => {
      if (!file || processing || returnAnalysisProcessing) return;
      setReturnAnalysisError(null);
      setReturnAnalysisSummary(null);
      setReturnAnalysisProcessing(true);
      setReturnAnalysisTaskStatus("queued");
      setReturnAnalysisProgress(1);
      setReturnAnalysisProgressMessage("Queued");
      returnPollErrorsRef.current = 0;
      try {
        const task = await startReturnAnalysisTask(file, { sourcePlatform: p.id });
        setReturnAnalysisTaskId(task.task_id || "");
        setReturnAnalysisTaskStatus(task.status || "queued");
        setReturnAnalysisProgress(Number.isFinite(task.progress) ? task.progress : 1);
        setReturnAnalysisProgressMessage(task.status === "queued" ? "Queued" : "Running");
        saveActiveTask(userScopeKey, p.id, { kind: "return_analysis", taskId: task.task_id || "" });
      } catch (e) {
        setReturnAnalysisError(e instanceof Error ? e.message : String(e));
        setReturnAnalysisTaskStatus("failed");
        setReturnAnalysisProgress(100);
        setReturnAnalysisProgressMessage("Failed");
        setReturnAnalysisTaskId("");
        setReturnAnalysisProcessing(false);
      }
    },
    [p.id, processing, returnAnalysisProcessing, userScopeKey],
  );

  useEffect(() => {
    if (!returnAnalysisTaskId) return;
    if (returnAnalysisTaskStatus === "success" || returnAnalysisTaskStatus === "failed") {
      setReturnAnalysisProcessing(false);
      return;
    }
    let cancelled = false;
    const effectUserScope = userScopeKey;
    const poll = async () => {
      if (cancelled || userScopeRef.current !== effectUserScope) return;
      try {
        const task = await fetchTaskStatus(returnAnalysisTaskId);
        if (cancelled || userScopeRef.current !== effectUserScope) return;
        setReturnAnalysisTaskStatus(task.status || "running");
        setReturnAnalysisProgress(Number.isFinite(task.progress) ? task.progress : 0);
        setReturnAnalysisProgressMessage(task.message || "");
        returnPollErrorsRef.current = 0;
        if (task.status === "success") {
          setReturnAnalysisProcessing(false);
          setReturnAnalysisProgressMessage("Completed. Analysis stored securely on server.");
          setReturnAnalysisSummary(task.summary || null);
          invalidateHistoryCache();
          refreshHistory({ bypassCache: true });
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
        if (task.status === "failed" || task.status === "cancelled" || task.status === "expired") {
          setReturnAnalysisProcessing(false);
          setReturnAnalysisError(task.error || "Return analysis task failed.");
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
      } catch (e) {
        if (cancelled || userScopeRef.current !== effectUserScope) return;
        returnPollErrorsRef.current += 1;
        if (returnPollErrorsRef.current >= 8) {
          setReturnAnalysisProcessing(false);
          setReturnAnalysisTaskStatus("failed");
          setReturnAnalysisError(e instanceof Error ? e.message : String(e));
          saveActiveTask(userScopeKey, p.id, null);
          return;
        }
        setReturnAnalysisProgressMessage("Temporary network issue. Retrying...");
      }
      if (!cancelled) {
        setTimeout(poll, TASK_POLL_MS);
      }
    };
    poll();
    return () => {
      cancelled = true;
    };
  }, [p.id, refreshHistory, returnAnalysisTaskId, returnAnalysisTaskStatus, userScopeKey]);

  useEffect(() => {
    if (!files.length && filesRequireReselection) {
      setFilesRequireReselection(false);
      setRestoreWarning("");
    }
  }, [files, filesRequireReselection]);

  useEffect(() => {
    if (!workspaceHydrated) return;
    saveWorkspaceSnapshot(userScopeKey, p.id, {
      outputLayout,
      sortBy,
      printDateTimeOnLabel,
      multiOrderAtBottom,
      separatePincodesEnabled,
      separatePincodes,
      detectSuspiciousBuyerEnabled,
      suspiciousMarkerPreviewEnabled,
      separateMultiOrderEnabled,
      loyalCustomerEnabled,
      loyalCustomerPreviewEnabled,
      userHistorySuborderId,
      printCustomMessage,
      customPrintMessage,
      processing,
      processed,
      progress,
      cropTaskId,
      cropTaskStatus,
      cropProgressMessage,
      lastMergedCropTaskId,
      outputArtifactName,
      outputArtifactMime,
      outputPlatformName,
      cropBillingMessage,
      cropTaskSummary,
      mergeError: mergeError || "",
      ocrProcessing,
      ocrError: ocrError || "",
      ocrTaskId,
      ocrTaskStatus,
      ocrProgress,
      ocrProgressMessage,
      returnAnalysisProcessing,
      returnAnalysisError: returnAnalysisError || "",
      returnAnalysisTaskId,
      returnAnalysisTaskStatus,
      returnAnalysisProgress,
      returnAnalysisProgressMessage,
      returnAnalysisSummary,
      ocrAutoStartedForCurrentFiles,
      ocrColumnPreset,
      ocrCustomColumns,
      ocrMaxWorkers,
      coinGateError,
      queuedFiles: toQueuedFileMetadata(files),
    });
  }, [
    coinGateError,
    cropProgressMessage,
    cropTaskId,
    cropTaskStatus,
    cropBillingMessage,
    cropTaskSummary,
    lastMergedCropTaskId,
    customPrintMessage,
    detectSuspiciousBuyerEnabled,
    suspiciousMarkerPreviewEnabled,
    files,
    loyalCustomerEnabled,
    loyalCustomerPreviewEnabled,
    mergeError,
    multiOrderAtBottom,
    ocrAutoStartedForCurrentFiles,
    ocrColumnPreset,
    ocrCustomColumns,
    ocrError,
    ocrMaxWorkers,
    ocrProcessing,
    ocrProgress,
    ocrProgressMessage,
    ocrTaskId,
    ocrTaskStatus,
    outputArtifactMime,
    outputArtifactName,
    outputPlatformName,
    cropBillingMessage,
    outputLayout,
    p.id,
    printCustomMessage,
    printDateTimeOnLabel,
    processed,
    processing,
    progress,
    returnAnalysisError,
    returnAnalysisProcessing,
    returnAnalysisProgress,
    returnAnalysisProgressMessage,
    returnAnalysisSummary,
    returnAnalysisTaskId,
    returnAnalysisTaskStatus,
    separateMultiOrderEnabled,
    separatePincodes,
    separatePincodesEnabled,
    sortBy,
    userHistorySuborderId,
    workspaceHydrated,
    userScopeKey,
  ]);
  const layoutLabel = useMemo(
    () => OUTPUT_LAYOUTS.find((x) => x.value === outputLayout)?.label ?? "",
    [outputLayout],
  );

  const isMeeshoLikeView = p.id === "meesho" || p.id === "flipkart";
  const clearActiveTask = useCallback(() => saveActiveTask(userScopeKey, p.id, null), [p.id, userScopeKey]);

  // Stable props bag for MeeshoNeonView so it can be safely memoized.
  // Recomputes only when one of its inputs actually changes.
  const meeshoWs = useMemo(
    () => ({
      files,
      filesRequireReselection,
      restoreWarning,
      hasFiles,
      drag,
      setDrag,
      addFiles,
      handleDrop,
      inputRef,
      outputLayout,
      setOutputLayout,
      sortBy,
      setSortBy,
      printDateTimeOnLabel,
      setPrintDateTimeOnLabel,
      multiOrderAtBottom,
      setMultiOrderAtBottom,
      separatePincodesEnabled,
      setSeparatePincodesEnabled,
      separatePincodes,
      setSeparatePincodes,
      detectSuspiciousBuyerEnabled,
      setDetectSuspiciousBuyerEnabled,
      suspiciousMarkerPreviewEnabled,
      setSuspiciousMarkerPreviewEnabled,
      separateMultiOrderEnabled,
      setSeparateMultiOrderEnabled,
      loyalCustomerEnabled,
      setLoyalCustomerEnabled,
      loyalCustomerPreviewEnabled,
      setLoyalCustomerPreviewEnabled,
      userHistorySuborderId,
      setUserHistorySuborderId,
      printCustomMessage,
      setPrintCustomMessage,
      customPrintMessage,
      setCustomPrintMessage,
      processing,
      processed,
      progress,
      outputPdfBytes,
      outputArtifactName,
      cropBillingMessage,
      cropTaskSummary,
      mergeError,
      ocrProcessing,
      ocrError,
      ocrTaskId,
      ocrTaskStatus,
      ocrProgress,
      ocrProgressMessage,
      returnAnalysisProcessing,
      returnAnalysisError,
      returnAnalysisTaskId,
      returnAnalysisTaskStatus,
      returnAnalysisProgress,
      returnAnalysisProgressMessage,
      returnAnalysisSummary,
      ocrColumnPreset,
      setOcrColumnPreset,
      ocrCustomColumns,
      setOcrCustomColumns,
      ocrMaxWorkers,
      setOcrMaxWorkers,
      ocrPresetOptions: OCR_COLUMN_PRESETS,
      coinGateError,
      balance,
      handleProcess,
      handleDownloadPdf,
      handleGenerateOcrExcel,
      handleStartReturnAnalysis,
      returnInputRef,
      setMergeError,
      setOcrError,
      setCoinGateError,
      setFiles,
      setProcessed,
      setProcessing,
      setProgress,
      cropTaskId,
      cropTaskStatus,
      cropProgressMessage,
      setCropTaskId,
      setCropTaskStatus,
      setCropProgressMessage,
      setOutputPdfBytes,
      setOutputArtifactName,
      setOutputArtifactMime,
      setCropTaskSummary,
      setOcrTaskId,
      setOcrTaskStatus,
      setOcrProgress,
      setOcrProgressMessage,
      setReturnAnalysisTaskId,
      setReturnAnalysisTaskStatus,
      setReturnAnalysisProgress,
      setReturnAnalysisProgressMessage,
      setReturnAnalysisError,
      setReturnAnalysisSummary,
      clearActiveTask,
      layoutLabel,
      cropHistory,
      historyDownloadJobId,
      handleDownloadHistoryJob,
    }),
    [
      files,
      filesRequireReselection,
      restoreWarning,
      hasFiles,
      drag,
      addFiles,
      handleDrop,
      outputLayout,
      sortBy,
      printDateTimeOnLabel,
      multiOrderAtBottom,
      separatePincodesEnabled,
      separatePincodes,
      detectSuspiciousBuyerEnabled,
      suspiciousMarkerPreviewEnabled,
      separateMultiOrderEnabled,
      loyalCustomerEnabled,
      loyalCustomerPreviewEnabled,
      userHistorySuborderId,
      printCustomMessage,
      customPrintMessage,
      processing,
      processed,
      cropTaskId,
      cropTaskStatus,
      cropProgressMessage,
      progress,
      outputPdfBytes,
      outputArtifactName,
      cropBillingMessage,
      cropTaskSummary,
      mergeError,
      ocrProcessing,
      ocrError,
      ocrTaskId,
      ocrTaskStatus,
      ocrProgress,
      ocrProgressMessage,
      returnAnalysisProcessing,
      returnAnalysisError,
      returnAnalysisTaskId,
      returnAnalysisTaskStatus,
      returnAnalysisProgress,
      returnAnalysisProgressMessage,
      returnAnalysisSummary,
      ocrColumnPreset,
      ocrCustomColumns,
      ocrMaxWorkers,
      coinGateError,
      balance,
      handleProcess,
      handleDownloadPdf,
      handleGenerateOcrExcel,
      handleStartReturnAnalysis,
      layoutLabel,
      cropHistory,
      historyDownloadJobId,
      handleDownloadHistoryJob,
      OCR_COLUMN_PRESETS,
      setProcessing,
      clearActiveTask,
    ],
  );

  if (isMeeshoLikeView) {
    return <MeeshoNeonView p={p} ws={meeshoWs} />;
  }

  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: brand.bgPage,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Top bar: back + current + platform switcher + status */}
      <div
        className="workspace-header-bar"
        style={{
          background: "rgba(14, 16, 22, 0.92)",
          backdropFilter: "blur(12px)",
          borderBottom: `1px solid ${brand.border}`,
          padding: "10px 20px",
          display: "grid",
          gridTemplateColumns: "auto minmax(0, 1fr) auto",
          alignItems: "center",
          gap: "10px 16px",
        }}
      >
        <div
          className="workspace-header-left"
          style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}
        >
          <Link
            to="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 13,
              fontWeight: 600,
              color: brand.textMuted,
              fontFamily: font,
              textDecoration: "none",
              padding: "6px 10px",
              borderRadius: 8,
              border: "1px solid transparent",
            }}
          >
            <span aria-hidden>←</span> All platforms
          </Link>
          <span style={{ color: "#CBD5E1", fontSize: 14 }}>/</span>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "5px 12px 5px 6px",
              borderRadius: 999,
              background: p.bg,
              border: `1px solid ${p.border}`,
            }}
          >
            <PlatformLogo p={p} size={24} />
            <span style={{ fontSize: 13, fontWeight: 700, color: brand.text, fontFamily: font }}>
              {p.name}
            </span>
          </div>
        </div>

        <nav
          className="workspace-header-nav"
          aria-label="Switch platform cropper"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            minWidth: 0,
            overflowX: "auto",
            overflowY: "hidden",
            padding: "4px 2px",
            WebkitOverflowScrolling: "touch",
            scrollbarWidth: "thin",
          }}
        >
          {PLATFORMS.map((plat) => {
            const active = plat.id === p.id;
            return (
              <Link
                key={plat.id}
                to={`/${plat.id}`}
                title={`${plat.name} cropper`}
                style={{
                  flexShrink: 0,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  padding: "4px 10px 4px 5px",
                  borderRadius: 999,
                  textDecoration: "none",
                  fontFamily: font,
                  fontSize: 11,
                  fontWeight: active ? 800 : 600,
                  color: active ? brand.text : brand.textMuted,
                  border: active ? `2px solid ${plat.color}` : `1px solid ${brand.border}`,
                  background: active ? plat.bg : "rgba(255,255,255,0.06)",
                  boxShadow: active ? `0 1px 6px ${plat.color}33` : "0 1px 2px rgba(15,23,42,0.04)",
                  transition: "background 0.15s, border-color 0.15s, color 0.15s",
                }}
              >
                <span
                  style={{
                    width: 22,
                    height: 22,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    overflow: "hidden",
                    borderRadius: 6,
                  }}
                >
                  <PlatformLogo p={plat} size={20} />
                </span>
                <span>{plat.name}</span>
              </Link>
            );
          })}
        </nav>

        <div
          className="workspace-header-status"
          style={{ display: "flex", alignItems: "center", justifyContent: "flex-end" }}
        >
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: "#86efac",
              fontFamily: font,
              padding: "4px 10px",
              borderRadius: 999,
              background: "rgba(22, 101, 52, 0.45)",
              border: "1px solid rgba(74, 222, 128, 0.35)",
              whiteSpace: "nowrap",
            }}
          >
            Ready to upload
          </span>
        </div>
      </div>

      <div className="workspace-body" style={{ display: "flex", flex: 1, minHeight: 0 }}>
        {/* Main column */}
        <div
          className="workspace-main"
          style={{
            flex: 1,
            minWidth: 0,
            padding: "24px 20px 32px 24px",
            overflow: "auto",
          }}
        >
          <div style={{ maxWidth: 680 }}>
            <p
              style={{
                margin: "0 0 6px",
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: p.color,
                fontFamily: font,
              }}
            >
              {p.name} · Label cropper
            </p>
            <h1
              style={{
                margin: "0 0 10px",
                fontFamily: font,
                fontWeight: 800,
                fontSize: "clamp(22px, 2.5vw, 28px)",
                color: brand.text,
                letterSpacing: "-0.6px",
                lineHeight: 1.2,
              }}
            >
              Upload invoices, get print-ready labels
            </h1>
            <p
              style={{
                margin: "0 0 28px",
                fontSize: 15,
                color: brand.textMuted,
                fontFamily: font,
                lineHeight: 1.55,
                maxWidth: 520,
              }}
            >
              Add one or more <strong style={{ color: brand.text }}>PDF</strong> files from {p.name}
              . We’ll detect label areas, crop them, and build one print-ready PDF (merged if you
              upload several files).
            </p>

            {/* Drop zone card */}
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDrag(true);
              }}
              onDragLeave={() => setDrag(false)}
              onDrop={handleDrop}
              onClick={() => !hasFiles && inputRef.current?.click()}
              style={{
                border: `2px dashed ${drag ? p.color : hasFiles ? "#CBD5E1" : "#94A3B8"}`,
                borderRadius: 20,
                background: drag ? `${p.color}18` : "rgba(22, 24, 32, 0.75)",
                padding: hasFiles ? "22px 22px" : "40px 28px 36px",
                cursor: hasFiles ? "default" : "pointer",
                transition: "border-color 0.2s, box-shadow 0.2s, background 0.2s",
                minHeight: hasFiles ? "auto" : 220,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: hasFiles ? "flex-start" : "center",
                boxShadow: drag
                  ? `0 0 0 4px ${p.color}18, 0 12px 40px rgba(15,23,42,0.06)`
                  : "0 4px 24px rgba(15, 23, 42, 0.06)",
              }}
            >
              {!hasFiles ? (
                <>
                  <div
                    style={{
                      width: 64,
                      height: 64,
                      borderRadius: 18,
                      background: `${p.color}14`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      marginBottom: 16,
                      transition: "transform 0.2s",
                      transform: drag ? "scale(1.06)" : "scale(1)",
                    }}
                  >
                    <UploadIcon color={p.color} size={28} />
                  </div>
                  <h2
                    style={{
                      margin: "0 0 8px",
                      fontFamily: font,
                      fontWeight: 700,
                      fontSize: 18,
                      color: brand.text,
                      textAlign: "center",
                    }}
                  >
                    Drop PDFs here
                  </h2>
                  <p
                    style={{
                      margin: "0 0 20px",
                      fontSize: 14,
                      color: brand.textMuted,
                      fontFamily: font,
                      textAlign: "center",
                      maxWidth: 360,
                      lineHeight: 1.5,
                    }}
                  >
                    Drag files into this box, or use the button below. Only PDF is supported.
                  </p>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      inputRef.current?.click();
                    }}
                    style={{
                      padding: "11px 24px",
                      borderRadius: 12,
                      background: p.color,
                      color: "#fff",
                      border: "none",
                      cursor: "pointer",
                      fontSize: 14,
                      fontWeight: 700,
                      fontFamily: font,
                      boxShadow: `0 6px 20px ${p.color}44`,
                    }}
                  >
                    Choose PDF files
                  </button>
                  <p
                    style={{
                      margin: "16px 0 0",
                      fontSize: 12,
                      color: brand.textDim,
                      fontFamily: font,
                    }}
                  >
                    Max ~50 MB per file · you can add several files at once
                  </p>
                </>
              ) : (
                <div style={{ width: "100%" }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      marginBottom: 16,
                      flexWrap: "wrap",
                      gap: 10,
                    }}
                  >
                    <div>
                      <p
                        style={{
                          margin: 0,
                          fontSize: 12,
                          fontWeight: 700,
                          color: brand.textMuted,
                          fontFamily: font,
                          textTransform: "uppercase",
                          letterSpacing: "0.06em",
                        }}
                      >
                        Queued files
                      </p>
                      <p
                        style={{
                          margin: "4px 0 0",
                          fontSize: 17,
                          fontWeight: 800,
                          color: brand.text,
                          fontFamily: font,
                        }}
                      >
                        {files.length} PDF{files.length !== 1 ? "s" : ""} ready
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => inputRef.current?.click()}
                      style={{
                        fontSize: 13,
                        padding: "8px 14px",
                        border: `2px solid ${p.color}`,
                        color: p.color,
                        background: "rgba(255,255,255,0.08)",
                        borderRadius: 10,
                        cursor: "pointer",
                        fontFamily: font,
                        fontWeight: 700,
                      }}
                    >
                      + Add more PDFs
                    </button>
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {files.map((f, i) => (
                      <FileItem
                        key={`${f.name}-${i}`}
                        file={f}
                        platform={p}
                        processed={processed}
                        onRemove={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>

            <input
              ref={inputRef}
              type="file"
              accept=".pdf"
              multiple
              style={{ display: "none" }}
              onChange={(e) => addFiles(e.target.files)}
            />

            {processing && (
              <div
                style={{
                  marginTop: 20,
                  background: "rgba(22, 24, 32, 0.85)",
                  border: `1px solid ${brand.border}`,
                  borderRadius: 16,
                  padding: "20px 22px",
                  boxShadow: "0 4px 20px rgba(15,23,42,0.05)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: 12,
                  }}
                >
                  <span
                    style={{
                      fontFamily: font,
                      fontWeight: 700,
                      fontSize: 15,
                      color: brand.text,
                    }}
                  >
                    Cropping &amp; sorting…
                  </span>
                  <span
                    style={{
                      fontSize: 14,
                      fontWeight: 700,
                      color: p.color,
                      fontFamily: font,
                    }}
                  >
                    {Math.min(Math.round(progress), 100)}%
                  </span>
                </div>
                <div
                  style={{
                    height: 8,
                    borderRadius: 999,
                    background: "#E2E8F0",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      height: "100%",
                      width: `${Math.min(progress, 100)}%`,
                      background: `linear-gradient(90deg, ${p.color}, ${p.color}cc)`,
                      borderRadius: 999,
                      transition: "width 0.16s ease",
                    }}
                  />
                </div>
                <p
                  style={{
                    margin: "12px 0 0",
                    fontSize: 12,
                    color: brand.textMuted,
                    fontFamily: font,
                    lineHeight: 1.45,
                  }}
                >
                  {cropProgressMessage?.trim() ||
                    "Reading pages · finding label edges · applying your sort order"}
                </p>
              </div>
            )}

            {mergeError && !processing && (
              <div
                style={{
                  marginTop: 20,
                  background: "rgba(127, 29, 29, 0.25)",
                  border: "1px solid rgba(248, 113, 113, 0.35)",
                  borderRadius: 16,
                  padding: "20px 22px",
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: 15,
                    fontWeight: 800,
                    color: "#fecaca",
                    fontFamily: font,
                    marginBottom: 8,
                  }}
                >
                  Could not build the PDF
                </p>
                <p
                  style={{
                    margin: "0 0 16px",
                    fontSize: 13,
                    color: "#fca5a5",
                    fontFamily: font,
                    lineHeight: 1.5,
                  }}
                >
                  {mergeError}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setMergeError(null);
                    setCoinGateError(false);
                  }}
                  style={{
                    padding: "8px 16px",
                    borderRadius: 10,
                    background: "rgba(255,255,255,0.08)",
                    border: "1px solid rgba(248, 113, 113, 0.45)",
                    cursor: "pointer",
                    fontFamily: font,
                    fontWeight: 600,
                    fontSize: 13,
                    color: "#fecaca",
                  }}
                >
                  Dismiss
                </button>
              </div>
            )}

            {ocrError && !ocrProcessing && (
              <div
                style={{
                  marginTop: 20,
                  background: "rgba(127, 29, 29, 0.25)",
                  border: "1px solid rgba(248, 113, 113, 0.35)",
                  borderRadius: 16,
                  padding: "20px 22px",
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: 15,
                    fontWeight: 800,
                    color: "#fecaca",
                    fontFamily: font,
                    marginBottom: 8,
                  }}
                >
                  Could not process OCR CSV
                </p>
                <p
                  style={{
                    margin: "0 0 16px",
                    fontSize: 13,
                    color: "#fca5a5",
                    fontFamily: font,
                    lineHeight: 1.5,
                  }}
                >
                  {ocrError}
                </p>
                <button
                  type="button"
                  onClick={() => setOcrError(null)}
                  style={{
                    padding: "8px 16px",
                    borderRadius: 10,
                    background: "rgba(255,255,255,0.08)",
                    border: "1px solid rgba(248, 113, 113, 0.45)",
                    cursor: "pointer",
                    fontFamily: font,
                    fontWeight: 600,
                    fontSize: 13,
                    color: "#fecaca",
                  }}
                >
                  Dismiss
                </button>
              </div>
            )}

            {coinGateError && !processing && (
              <div
                style={{
                  marginTop: 20,
                  background: "rgba(120, 53, 15, 0.35)",
                  border: "1px solid rgba(253, 224, 71, 0.35)",
                  borderRadius: 16,
                  padding: "20px 22px",
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: 15,
                    fontWeight: 800,
                    color: "#fde68a",
                    fontFamily: font,
                    marginBottom: 8,
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                  }}
                >
                  <CoinIcon size={20} alt="" />
                  Not enough coins
                </p>
                <p
                  style={{
                    margin: "0 0 16px",
                    fontSize: 13,
                    color: "#fcd34d",
                    fontFamily: font,
                    lineHeight: 1.5,
                  }}
                >
                  Premium crop billing is{" "}
                  <strong>{PREMIUM_CROP_COIN_COST_PER_LABEL} coin per label</strong> when any premium
                  feature is enabled. You have <strong>{balance}</strong>. Contact admin to add coins.
                </p>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                  <Link
                    to="/wallet"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      padding: "10px 18px",
                      borderRadius: 10,
                      background: "#D97706",
                      color: "#fff",
                      fontWeight: 700,
                      fontSize: 14,
                      fontFamily: font,
                      textDecoration: "none",
                    }}
                  >
                    Go to wallet
                  </Link>
                  <button
                    type="button"
                    onClick={() => setCoinGateError(false)}
                    style={{
                      padding: "10px 16px",
                      borderRadius: 10,
                      background: "rgba(255,255,255,0.08)",
                      border: "1px solid rgba(253, 224, 71, 0.4)",
                      cursor: "pointer",
                      fontFamily: font,
                      fontWeight: 600,
                      fontSize: 13,
                      color: "#fef3c7",
                    }}
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            {processed && outputPdfBytes && (
              <div
                style={{
                  marginTop: 20,
                  background: "rgba(22, 101, 52, 0.35)",
                  border: "1px solid rgba(74, 222, 128, 0.35)",
                  borderRadius: 16,
                  padding: "20px 22px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: "50%",
                      background: "#16A34A",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <CheckIcon size={14} />
                  </div>
                  <span
                    style={{
                      fontFamily: font,
                      fontWeight: 800,
                      fontSize: 17,
                      color: "#bbf7d0",
                    }}
                  >
                    {files.length > 1 ? "Merged PDF ready" : "PDF ready"}
                  </span>
                </div>
                <p
                  style={{
                    fontSize: 14,
                    color: "#86efac",
                    fontFamily: font,
                    marginBottom: 16,
                    lineHeight: 1.55,
                  }}
                >
                  {p.id === "meesho" ? (
                    <>
                      Cropped and sorted on the server from <strong>{files.length}</strong> PDF
                      {files.length !== 1 ? "s" : ""}. Sort:{" "}
                      <strong>{SORT_OPTIONS.find((o) => o.value === sortBy)?.label}</strong>. Print
                      mode: <strong>{layoutLabel}</strong>.
                    </>
                  ) : files.length > 1 ? (
                    <>
                      Combined <strong>{files.length}</strong> uploaded PDFs into{" "}
                      <strong>one</strong> file. Sort:{" "}
                      <strong>{SORT_OPTIONS.find((o) => o.value === sortBy)?.label}</strong>. Print
                      mode: <strong>{layoutLabel}</strong>.
                    </>
                  ) : (
                    <>
                      Output is a single PDF from your file. Sort:{" "}
                      <strong>{SORT_OPTIONS.find((o) => o.value === sortBy)?.label}</strong>. Print
                      mode: <strong>{layoutLabel}</strong>.
                    </>
                  )}
                </p>
                <CourierCountsPanel summary={cropTaskSummary} platformId={p.id} />
                <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={handleDownloadPdf}
                    style={{
                      padding: "10px 20px",
                      borderRadius: 11,
                      background: "#16A34A",
                      color: "#fff",
                      border: "none",
                      cursor: "pointer",
                      fontSize: 14,
                      fontWeight: 700,
                      fontFamily: font,
                    }}
                  >
                    {outputArtifactName.toLowerCase().endsWith(".zip")
                      ? "⬇ Download result ZIP"
                      : "⬇ Download PDF"}
                  </button>
                </div>
              </div>
            )}

          </div>
        </div>

        {/* Options column */}
        <aside
          className="workspace-aside"
          style={{
            width: 320,
            flexShrink: 0,
            background: brand.bgCardSolid,
            borderLeft: `1px solid ${brand.border}`,
            display: "flex",
            flexDirection: "column",
            overflow: "auto",
            boxShadow: "-8px 0 32px rgba(15,23,42,0.04)",
          }}
        >
          <div style={{ padding: "22px 22px 18px", borderBottom: `1px solid ${brand.border}` }}>
            <h2
              style={{
                margin: 0,
                fontFamily: font,
                fontWeight: 800,
                fontSize: 16,
                color: brand.text,
              }}
            >
              Options
            </h2>
            <p
              style={{ margin: "6px 0 0", fontSize: 13, color: brand.textMuted, fontFamily: font }}
            >
              Set print format and sort order anytime. Upload PDFs to run the cropper.
            </p>
          </div>

          <div
            style={{
              padding: "18px 20px 12px",
              display: "flex",
              flexDirection: "column",
              gap: 20,
              flex: 1,
            }}
          >
            <section>
              <h3
                style={{
                  margin: "0 0 4px",
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: brand.textMuted,
                  fontFamily: font,
                }}
              >
                How do you want to print?
              </h3>
              <p
                style={{ margin: "0 0 12px", fontSize: 12, color: brand.textDim, fontFamily: font }}
              >
                Pick one — label roll or keep invoice.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                {OUTPUT_LAYOUTS.map((opt) => {
                  const active = outputLayout === opt.value;
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setOutputLayout(opt.value)}
                      style={{
                        textAlign: "left",
                        padding: "14px 12px",
                        borderRadius: 14,
                        border: active ? `2px solid ${p.color}` : `2px solid ${brand.border}`,
                        background: active ? p.bg : "rgba(255,255,255,0.04)",
                        cursor: "pointer",
                        transition: "border-color 0.15s, background 0.15s, transform 0.15s",
                        fontFamily: font,
                        display: "flex",
                        flexDirection: "column",
                        gap: 6,
                        minHeight: 108,
                      }}
                    >
                      <span style={{ fontSize: 22, lineHeight: 1 }}>{opt.icon}</span>
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 800,
                          color: brand.text,
                          letterSpacing: "-0.2px",
                        }}
                      >
                        {opt.label}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: brand.textMuted,
                          lineHeight: 1.35,
                          fontWeight: 500,
                        }}
                      >
                        {opt.hint}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>

            <section>
              <h3
                style={{
                  margin: "0 0 10px",
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: brand.textMuted,
                  fontFamily: font,
                }}
              >
                Order labels by
              </h3>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {SORT_OPTIONS.map((opt) => {
                  const active = sortBy === opt.value;
                  return (
                    <label
                      key={opt.value}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "10px 12px",
                        cursor: "pointer",
                        border: `1.5px solid ${active ? p.color + "99" : brand.border}`,
                        borderRadius: 12,
                        background: active ? p.bg : "rgba(255,255,255,0.05)",
                        transition: "all 0.15s",
                      }}
                    >
                      <input
                        type="radio"
                        name="sortBy"
                        value={opt.value}
                        checked={active}
                        onChange={(e) => setSortBy(e.target.value)}
                        style={{
                          accentColor: p.color,
                          width: 15,
                          height: 15,
                          flexShrink: 0,
                          cursor: "pointer",
                        }}
                      />
                      <span
                        style={{
                          fontSize: 13,
                          fontFamily: font,
                          color: active ? brand.text : brand.textMuted,
                          fontWeight: active ? 700 : 500,
                          flex: 1,
                        }}
                      >
                        {opt.label}
                      </span>
                      {active && (
                        <div
                          style={{
                            width: 18,
                            height: 18,
                            borderRadius: "50%",
                            background: p.color,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexShrink: 0,
                          }}
                        >
                          <CheckIcon size={9} />
                        </div>
                      )}
                    </label>
                  );
                })}
              </div>
            </section>

            {p.id === "meesho" && (
              <section>
                <h3
                  style={{
                    margin: "0 0 10px",
                    fontSize: 11,
                    fontWeight: 800,
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    color: brand.textMuted,
                    fontFamily: font,
                  }}
                >
                  Label extras
                </h3>
                <p
                  style={{
                    margin: "-2px 0 10px",
                    fontSize: 11,
                    color: brand.textMuted,
                    fontFamily: font,
                    lineHeight: 1.45,
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 6,
                  }}
                >
                  <CoinIcon size={14} style={{ marginTop: 1 }} alt="" />
                  <span>
                    Premium billing: <strong>{PREMIUM_CROP_COIN_COST_PER_LABEL} coin per label</strong>{" "}
                    when any premium option is enabled · Your balance: <strong>{balance}</strong>{" "}
                    <Link to="/wallet" style={{ color: p.color, fontWeight: 700 }}>
                      Top up
                    </Link>
                  </span>
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      padding: "10px 12px",
                      cursor: "pointer",
                      border: `1.5px solid ${brand.border}`,
                      borderRadius: 12,
                      background: "rgba(255,255,255,0.05)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={printDateTimeOnLabel}
                      onChange={(e) => setPrintDateTimeOnLabel(e.target.checked)}
                      style={{
                        accentColor: p.color,
                        width: 15,
                        height: 15,
                        marginTop: 2,
                        flexShrink: 0,
                        cursor: "pointer",
                      }}
                    />
                    <span
                      style={{
                        fontSize: 13,
                        fontFamily: font,
                        color: brand.textMuted,
                        lineHeight: 1.4,
                      }}
                    >
                      Print date time on label
                    </span>
                  </label>
                  <label
                    style={{
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 10,
                      padding: "10px 12px",
                      cursor: "pointer",
                      border: `1.5px solid ${brand.border}`,
                      borderRadius: 12,
                      background: "rgba(255,255,255,0.05)",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={multiOrderAtBottom}
                      onChange={(e) => setMultiOrderAtBottom(e.target.checked)}
                      style={{
                        accentColor: p.color,
                        width: 15,
                        height: 15,
                        marginTop: 2,
                        flexShrink: 0,
                        cursor: "pointer",
                      }}
                    />
                    <span
                      style={{
                        fontSize: 13,
                        fontFamily: font,
                        color: brand.textMuted,
                        lineHeight: 1.4,
                      }}
                    >
                      Multi-qty invoices last
                    </span>
                  </label>
                </div>
              </section>
            )}

            <div style={{ borderTop: `1px solid ${brand.border}`, marginTop: 4 }} />

            <div
              style={{
                marginTop: 2,
                ...(!hasFiles && !processing && !processed
                  ? {
                      padding: "14px 12px 12px",
                      borderRadius: 16,
                      border: `2px dashed ${p.color}55`,
                      background: `${p.color}0D`,
                      boxShadow: `0 0 0 1px ${p.color}18, 0 8px 28px ${p.color}14`,
                    }
                  : {
                      padding: 0,
                      borderRadius: 0,
                      border: "none",
                      background: "transparent",
                      boxShadow: "none",
                    }),
                transition: "border-color 0.2s, background 0.2s, box-shadow 0.2s, padding 0.2s",
              }}
            >
              <p
                style={{
                  margin: "0 0 10px",
                  fontSize: 11,
                  fontWeight: 800,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: !hasFiles && !processing && !processed ? p.color : "#64748B",
                  fontFamily: font,
                  textAlign: "center",
                }}
              >
                {filesRequireReselection
                  ? "Reselect PDFs to continue"
                  : !hasFiles && !processing && !processed
                  ? "Next: run cropper"
                  : hasFiles && !processing && !processed
                    ? "Ready to crop"
                    : processing
                      ? "Processing"
                      : "Done"}
              </p>
              <button
                type="button"
                onClick={handleProcess}
                disabled={!hasFiles || processing || processed}
                style={{
                  width: "100%",
                  padding: "14px 16px",
                  background: processing || processed ? "#94A3B8" : hasFiles ? p.color : "#94A3B8",
                  color: "#fff",
                  border: "none",
                  borderRadius: 14,
                  cursor:
                    hasFiles && !processing && !processed
                      ? "pointer"
                      : "not-allowed",
                  fontFamily: font,
                  fontWeight: 800,
                  fontSize: 15,
                  letterSpacing: "-0.2px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  opacity:
                    !hasFiles && !processing && !processed ? 0.92 : 1,
                  boxShadow:
                    hasFiles && !processing && !processed
                      ? `0 8px 24px ${p.color}50`
                      : "none",
                }}
              >
                {processing ? (
                  <>
                    <div
                      style={{
                        width: 16,
                        height: 16,
                        borderRadius: "50%",
                        border: "2px solid rgba(255,255,255,0.35)",
                        borderTopColor: "#fff",
                        animation: "spin 0.7s linear infinite",
                      }}
                    />
                    Working…
                  </>
                ) : processed ? (
                  "✓ Finished"
                ) : (
                  filesRequireReselection ? "Reselect PDFs first" : "⚡ Crop labels now"
                )}
              </button>
              {!hasFiles && !processing && !processed && (
                <p
                  style={{
                    margin: "10px 0 0",
                    fontSize: 12,
                    color: brand.textMuted,
                    textAlign: "center",
                    fontFamily: font,
                    lineHeight: 1.45,
                  }}
                >
                  Upload one or more PDFs on the left to activate this button.
                </p>
              )}
            </div>

            {hasFiles && !processing && !processed && (
              <p
                style={{
                  margin: "4px 0 0",
                  fontSize: 12,
                  color: brand.textMuted,
                  textAlign: "center",
                  fontFamily: font,
                  lineHeight: 1.5,
                }}
              >
                Output: <strong>{layoutLabel}</strong>
              </p>
            )}
          </div>

          <div
            style={{
              padding: "14px 20px 20px",
              borderTop: `1px solid ${brand.border}`,
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {[
              { emoji: "✓", text: "Detects labels inside messy invoices" },
              { emoji: "✓", text: "Many PDFs in one go" },
              { emoji: "✓", text: "One PDF download — merged when needed" },
            ].map((item) => (
              <div
                key={item.text}
                style={{
                  display: "flex",
                  alignItems: "flex-start",
                  gap: 10,
                  fontSize: 12,
                  color: brand.textMuted,
                  fontFamily: font,
                  lineHeight: 1.45,
                }}
              >
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 800,
                    color: p.color,
                    flexShrink: 0,
                    marginTop: 1,
                  }}
                >
                  {item.emoji}
                </span>
                <span>{item.text}</span>
              </div>
            ))}
          </div>
        </aside>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @media (max-width: 900px) {
          .workspace-header-bar {
            grid-template-columns: 1fr auto !important;
            grid-template-rows: auto auto;
          }
          .workspace-header-left {
            grid-column: 1;
            grid-row: 1;
          }
          .workspace-header-status {
            grid-column: 2;
            grid-row: 1;
            justify-self: end;
          }
          .workspace-header-nav {
            grid-column: 1 / -1;
            grid-row: 2;
            justify-content: flex-start !important;
          }
        }
        @media (max-width: 960px) {
          .workspace-body { flex-direction: column !important; }
          .workspace-aside {
            width: 100% !important;
            border-left: none !important;
            border-top: 1px solid rgba(148, 163, 184, 0.2);
            box-shadow: none !important;
          }
        }
      `}</style>
    </div>
  );
}
