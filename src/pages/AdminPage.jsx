import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ADMIN_OCR_PLATFORMS,
  adminCreditUserWallet,
  downloadAdminUserMasterCsv,
  downloadAdminUserSuspiciousCsv,
  exportAdminRoleAuditCsv,
  fetchAdminJobs,
  fetchAdminMetrics,
  fetchAdminOcrTaskRows,
  fetchAdminOcrTasks,
  fetchAdminWalletAudit,
  fetchAdminReturnTaskRows,
  fetchAdminReturnTasks,
  fetchAdminRoleAudit,
  fetchAdminRoleAuditCursor,
  fetchAdminUsersCursor,
  updateAdminUsersRoleBulk,
  updateAdminUserRole,
} from "../api/adminApi.js";

const PLATFORM_LABELS = {
  meesho: "Meesho",
  flipkart: "Flipkart",
};
import { useAuth } from "../auth/AuthContext.jsx";
import { brand, font } from "../theme/brandTheme.js";

const USERS_PAGE_SIZE = 50;
const AUDIT_PAGE_SIZE = 12;
const USER_ROW_HEIGHT = 92;
const USER_TABLE_HEIGHT = 360;
const AUDIT_LIST_HEIGHT = 360;
const WALLET_AUDIT_PAGE_SIZE = 20;
const ADMIN_UI_PREFS_KEY = "cropperhub_admin_ui_prefs";
const CSV_COLUMNS = [
  "id",
  "created_at",
  "actor_user_id",
  "actor_email",
  "actor_name",
  "target_user_id",
  "target_email",
  "target_name",
  "prev_is_admin",
  "next_is_admin",
];

function StatCard({ label, value, hint }) {
  return (
    <div
      style={{
        borderRadius: 14,
        border: `1px solid ${brand.border}`,
        background: "rgba(255,255,255,0.03)",
        padding: "14px 14px 12px",
      }}
    >
      <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12, fontWeight: 700 }}>{label}</div>
      <div style={{ color: brand.text, fontFamily: font, fontSize: 28, fontWeight: 800, marginTop: 4 }}>
        {value}
      </div>
      {hint ? (
        <div style={{ color: brand.textDim, fontFamily: font, fontSize: 11.5, marginTop: 4 }}>{hint}</div>
      ) : null}
    </div>
  );
}

function formatCreatedAt(value) {
  if (!value) return "-";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function dateInputValue(d) {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function loadAdminUiPrefs() {
  try {
    const raw = localStorage.getItem(ADMIN_UI_PREFS_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch {
    return null;
  }
}

function sanitizeColumns(value) {
  if (!Array.isArray(value)) return CSV_COLUMNS;
  return value.filter((col) => CSV_COLUMNS.includes(col));
}

function splitCounts(options) {
  const o = options && typeof options === "object" ? options : {};
  return {
    normal: Number(o.normal_pages || 0),
    suspicious: Number(o.risky_pages || 0),
    pincode: Number(o.selected_pincode_pages || 0),
    manualCustomers: Number(o.manual_high_risk_customers_total || 0),
    manualSuborders: Number(o.manual_high_risk_suborders_total || 0),
  };
}

export default function AdminPage() {
  const { user } = useAuth();
  const currentUserEmail = (user?.email || "").toLowerCase();
  const savedPrefs = useMemo(() => loadAdminUiPrefs(), []);

  const [metrics, setMetrics] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(true);
  const [metricsError, setMetricsError] = useState("");

  const [searchInput, setSearchInput] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [cursor, setCursor] = useState(null);
  const [cursorHistory, setCursorHistory] = useState([]);
  const [nextCursor, setNextCursor] = useState(null);
  const [cursorPage, setCursorPage] = useState(1);
  const [usersViewMode, setUsersViewMode] = useState(
    savedPrefs?.usersViewMode === "infinite" ? "infinite" : "paged",
  );
  const [usersSort, setUsersSort] = useState(
    (() => {
      const saved = String(savedPrefs?.usersSort || "").trim();
      // Migrate old "highest/lowest" expectation to label-count sort.
      if (saved === "email_desc") return "labels_desc";
      if (saved === "email_asc") return "labels_asc";
      if (
        saved === "labels_desc" ||
        saved === "labels_asc" ||
        saved === "risky_desc" ||
        saved === "risky_asc" ||
        saved === "default"
      ) {
        return saved;
      }
      return "default";
    })(),
  );
  const [infiniteCursor, setInfiniteCursor] = useState(null);
  const [infiniteHasMore, setInfiniteHasMore] = useState(false);
  const [infiniteLoadingMore, setInfiniteLoadingMore] = useState(false);

  const [users, setUsers] = useState([]);
  const [usersTotal, setUsersTotal] = useState(0);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState("");
  const [pendingUserId, setPendingUserId] = useState(null);
  const [pendingBulk, setPendingBulk] = useState(false);
  const [roleError, setRoleError] = useState("");
  const [walletCreditPending, setWalletCreditPending] = useState(false);
  const [walletCreditError, setWalletCreditError] = useState("");
  const [walletCreditSuccess, setWalletCreditSuccess] = useState("");
  const [walletAuditEvents, setWalletAuditEvents] = useState([]);
  const [walletAuditTotal, setWalletAuditTotal] = useState(0);
  const [walletAuditPage, setWalletAuditPage] = useState(1);
  const [walletAuditLoading, setWalletAuditLoading] = useState(false);
  const [walletAuditError, setWalletAuditError] = useState("");
  const [walletAuditQuery, setWalletAuditQuery] = useState("");
  const [walletAuditAppliedQuery, setWalletAuditAppliedQuery] = useState("");
  const [masterDataError, setMasterDataError] = useState("");
  const [suspiciousDataError, setSuspiciousDataError] = useState("");
  const [downloadingMasterUserId, setDownloadingMasterUserId] = useState(null);
  // Platform-scoped downloads run alongside the legacy combined download.
  // Tracking the (userId, platform) pair lets multiple buttons render the
  // correct disabled / "Downloading..." state independently.
  const [downloadingMasterPlatformKey, setDownloadingMasterPlatformKey] = useState("");
  const [downloadingSuspiciousUserId, setDownloadingSuspiciousUserId] = useState(null);
  const [downloadingSuspiciousPlatformKey, setDownloadingSuspiciousPlatformKey] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState([]);

  const [auditEvents, setAuditEvents] = useState([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [auditPage, setAuditPage] = useState(1);
  const [auditViewMode, setAuditViewMode] = useState(
    savedPrefs?.auditViewMode === "infinite" ? "infinite" : "paged",
  );
  const [auditInfiniteCursor, setAuditInfiniteCursor] = useState(null);
  const [auditInfiniteHasMore, setAuditInfiniteHasMore] = useState(false);
  const [auditInfiniteLoadingMore, setAuditInfiniteLoadingMore] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState("");
  const [auditActorFilter, setAuditActorFilter] = useState("");
  const [auditTargetFilter, setAuditTargetFilter] = useState("");
  const [auditFromDate, setAuditFromDate] = useState("");
  const [auditToDate, setAuditToDate] = useState("");
  const [auditAppliedFilters, setAuditAppliedFilters] = useState({
    actor: "",
    target: "",
    from: "",
    to: "",
  });
  const [csvColumns, setCsvColumns] = useState(sanitizeColumns(savedPrefs?.csvColumns));
  const [ocrQuery, setOcrQuery] = useState("");
  const [ocrAppliedQuery, setOcrAppliedQuery] = useState("");
  const [ocrTasks, setOcrTasks] = useState([]);
  const [ocrTasksTotal, setOcrTasksTotal] = useState(0);
  const [ocrTasksPage, setOcrTasksPage] = useState(1);
  const [ocrTasksLoading, setOcrTasksLoading] = useState(false);
  const [ocrTasksError, setOcrTasksError] = useState("");
  const [selectedOcrTaskId, setSelectedOcrTaskId] = useState("");
  const [ocrRowsQuery, setOcrRowsQuery] = useState("");
  const [ocrRows, setOcrRows] = useState([]);
  const [ocrRowsTotal, setOcrRowsTotal] = useState(0);
  const [ocrRowsPage, setOcrRowsPage] = useState(1);
  const [ocrRowsLoading, setOcrRowsLoading] = useState(false);
  const [ocrRowsError, setOcrRowsError] = useState("");
  const [returnQuery, setReturnQuery] = useState("");
  const [returnAppliedQuery, setReturnAppliedQuery] = useState("");
  const [returnTasks, setReturnTasks] = useState([]);
  const [returnTasksTotal, setReturnTasksTotal] = useState(0);
  const [returnTasksPage, setReturnTasksPage] = useState(1);
  const [returnTasksLoading, setReturnTasksLoading] = useState(false);
  const [returnTasksError, setReturnTasksError] = useState("");
  const [selectedReturnTaskId, setSelectedReturnTaskId] = useState("");
  const [returnRowsQuery, setReturnRowsQuery] = useState("");
  const [returnRows, setReturnRows] = useState([]);
  const [returnRowsTotal, setReturnRowsTotal] = useState(0);
  const [returnRowsPage, setReturnRowsPage] = useState(1);
  const [returnRowsLoading, setReturnRowsLoading] = useState(false);
  const [returnRowsError, setReturnRowsError] = useState("");
  const [adminJobs, setAdminJobs] = useState([]);
  const [adminJobsTotal, setAdminJobsTotal] = useState(0);
  const [adminJobsPage, setAdminJobsPage] = useState(1);
  const [adminJobsLoading, setAdminJobsLoading] = useState(false);
  const [adminJobsError, setAdminJobsError] = useState("");

  const totalPages = Math.max(1, Math.ceil(usersTotal / USERS_PAGE_SIZE));
  const auditOffset = (auditPage - 1) * AUDIT_PAGE_SIZE;
  const auditTotalPages = Math.max(1, Math.ceil(auditTotal / AUDIT_PAGE_SIZE));
  const OCR_TASKS_PAGE_SIZE = 20;
  const OCR_ROWS_PAGE_SIZE = 30;
  const RETURN_TASKS_PAGE_SIZE = 20;
  const RETURN_ROWS_PAGE_SIZE = 30;
  const ADMIN_JOBS_PAGE_SIZE = 20;
  const ocrTasksOffset = (ocrTasksPage - 1) * OCR_TASKS_PAGE_SIZE;
  const ocrRowsOffset = (ocrRowsPage - 1) * OCR_ROWS_PAGE_SIZE;
  const returnTasksOffset = (returnTasksPage - 1) * RETURN_TASKS_PAGE_SIZE;
  const returnRowsOffset = (returnRowsPage - 1) * RETURN_ROWS_PAGE_SIZE;
  const adminJobsOffset = (adminJobsPage - 1) * ADMIN_JOBS_PAGE_SIZE;
  const walletAuditOffset = (walletAuditPage - 1) * WALLET_AUDIT_PAGE_SIZE;
  const walletAuditTotalPages = Math.max(1, Math.ceil((walletAuditTotal || 0) / WALLET_AUDIT_PAGE_SIZE));

  const loadMetrics = useCallback(async () => {
    setMetricsLoading(true);
    setMetricsError("");
    try {
      const data = await fetchAdminMetrics();
      setMetrics(data);
    } catch (err) {
      setMetrics(null);
      setMetricsError(err instanceof Error ? err.message : "Could not load admin metrics.");
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  const loadUsers = useCallback(
    async ({ bypassCache = false } = {}) => {
      setUsersLoading(true);
      setUsersError("");
      try {
        const data = await fetchAdminUsersCursor({
          query: appliedQuery,
          limit: USERS_PAGE_SIZE,
          cursor: usersViewMode === "paged" ? cursor : null,
          sort: usersSort,
          bypassCache,
        });
        setUsers(data.users);
        setUsersTotal(data.total);
        if (usersViewMode === "paged") {
          setNextCursor(data.nextCursor ?? null);
        } else {
          setInfiniteCursor(data.nextCursor ?? null);
          setInfiniteHasMore(Boolean(data.hasMore));
          setNextCursor(null);
        }
      } catch (err) {
        setUsers([]);
        setUsersTotal(0);
        setNextCursor(null);
        setInfiniteCursor(null);
        setInfiniteHasMore(false);
        setUsersError(err instanceof Error ? err.message : "Could not load users.");
      } finally {
        setUsersLoading(false);
      }
    },
    [appliedQuery, cursor, usersSort, usersViewMode],
  );

  const loadMoreUsers = useCallback(async () => {
    if (usersViewMode !== "infinite") return;
    if (infiniteLoadingMore || !infiniteHasMore || infiniteCursor == null) return;
    setInfiniteLoadingMore(true);
    try {
      const data = await fetchAdminUsersCursor({
        query: appliedQuery,
        limit: USERS_PAGE_SIZE,
        cursor: infiniteCursor,
        sort: usersSort,
      });
      setUsers((prev) => {
        const known = new Set(prev.map((x) => x.id));
        const append = (data.users || []).filter((x) => !known.has(x.id));
        return [...prev, ...append];
      });
      setInfiniteCursor(data.nextCursor ?? null);
      setInfiniteHasMore(Boolean(data.hasMore));
      setUsersTotal(data.total);
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : "Could not load more users.");
    } finally {
      setInfiniteLoadingMore(false);
    }
  }, [appliedQuery, infiniteCursor, infiniteHasMore, infiniteLoadingMore, usersSort, usersViewMode]);

  useEffect(() => {
    setCursor(null);
    setCursorHistory([]);
    setCursorPage(1);
    setInfiniteCursor(null);
    setInfiniteHasMore(false);
  }, [usersSort]);

  const loadAudit = useCallback(
    async ({ bypassCache = false } = {}) => {
      setAuditLoading(true);
      setAuditError("");
      try {
        const fromDate = auditAppliedFilters.from ? `${auditAppliedFilters.from}T00:00:00.000Z` : "";
        const toDate = auditAppliedFilters.to ? `${auditAppliedFilters.to}T23:59:59.999Z` : "";
        if (auditViewMode === "paged") {
          const data = await fetchAdminRoleAudit({
            actorQuery: auditAppliedFilters.actor,
            targetQuery: auditAppliedFilters.target,
            fromDate,
            toDate,
            limit: AUDIT_PAGE_SIZE,
            offset: auditOffset,
            bypassCache,
          });
          setAuditEvents(data.events);
          setAuditTotal(data.total);
          setAuditInfiniteCursor(null);
          setAuditInfiniteHasMore(false);
        } else {
          const data = await fetchAdminRoleAuditCursor({
            actorQuery: auditAppliedFilters.actor,
            targetQuery: auditAppliedFilters.target,
            fromDate,
            toDate,
            limit: AUDIT_PAGE_SIZE,
            cursor: null,
            bypassCache,
          });
          setAuditEvents(data.events);
          setAuditTotal(data.total);
          setAuditInfiniteCursor(data.nextCursor ?? null);
          setAuditInfiniteHasMore(Boolean(data.hasMore));
        }
      } catch (err) {
        setAuditEvents([]);
        setAuditTotal(0);
        setAuditInfiniteCursor(null);
        setAuditInfiniteHasMore(false);
        setAuditError(err instanceof Error ? err.message : "Could not load role audit.");
      } finally {
        setAuditLoading(false);
      }
    },
    [
      auditAppliedFilters.actor,
      auditAppliedFilters.from,
      auditAppliedFilters.target,
      auditAppliedFilters.to,
      auditOffset,
      auditViewMode,
    ],
  );

  const loadMoreAudit = useCallback(async () => {
    if (auditViewMode !== "infinite") return;
    if (auditInfiniteLoadingMore || !auditInfiniteHasMore || auditInfiniteCursor == null) return;
    setAuditInfiniteLoadingMore(true);
    try {
      const data = await fetchAdminRoleAuditCursor({
        actorQuery: auditAppliedFilters.actor,
        targetQuery: auditAppliedFilters.target,
        fromDate: auditAppliedFilters.from ? `${auditAppliedFilters.from}T00:00:00.000Z` : "",
        toDate: auditAppliedFilters.to ? `${auditAppliedFilters.to}T23:59:59.999Z` : "",
        limit: AUDIT_PAGE_SIZE,
        cursor: auditInfiniteCursor,
      });
      setAuditEvents((prev) => {
        const known = new Set(prev.map((x) => x.id));
        const append = (data.events || []).filter((x) => !known.has(x.id));
        return [...prev, ...append];
      });
      setAuditTotal(data.total);
      setAuditInfiniteCursor(data.nextCursor ?? null);
      setAuditInfiniteHasMore(Boolean(data.hasMore));
    } catch (err) {
      setAuditError(err instanceof Error ? err.message : "Could not load more audit rows.");
    } finally {
      setAuditInfiniteLoadingMore(false);
    }
  }, [
    auditAppliedFilters.actor,
    auditAppliedFilters.from,
    auditAppliedFilters.target,
    auditAppliedFilters.to,
    auditInfiniteCursor,
    auditInfiniteHasMore,
    auditInfiniteLoadingMore,
    auditViewMode,
  ]);

  const loadOcrTasks = useCallback(
    async ({ bypassCache = false } = {}) => {
      setOcrTasksLoading(true);
      setOcrTasksError("");
      try {
        const data = await fetchAdminOcrTasks({
          query: ocrAppliedQuery,
          limit: OCR_TASKS_PAGE_SIZE,
          offset: ocrTasksOffset,
          bypassCache,
        });
        setOcrTasks(data.tasks);
        setOcrTasksTotal(data.total);
        if (data.tasks.length && !selectedOcrTaskId) {
          setSelectedOcrTaskId(data.tasks[0].task_id || "");
        }
      } catch (err) {
        setOcrTasks([]);
        setOcrTasksTotal(0);
        setOcrTasksError(err instanceof Error ? err.message : "Could not load OCR tasks.");
      } finally {
        setOcrTasksLoading(false);
      }
    },
    [ocrAppliedQuery, ocrTasksOffset, selectedOcrTaskId],
  );

  const loadOcrRows = useCallback(
    async ({ bypassCache = false } = {}) => {
      if (!selectedOcrTaskId) {
        setOcrRows([]);
        setOcrRowsTotal(0);
        return;
      }
      setOcrRowsLoading(true);
      setOcrRowsError("");
      try {
        const data = await fetchAdminOcrTaskRows({
          taskId: selectedOcrTaskId,
          query: ocrRowsQuery.trim(),
          limit: OCR_ROWS_PAGE_SIZE,
          offset: ocrRowsOffset,
          bypassCache,
        });
        setOcrRows(data.rows);
        setOcrRowsTotal(data.total);
      } catch (err) {
        setOcrRows([]);
        setOcrRowsTotal(0);
        setOcrRowsError(err instanceof Error ? err.message : "Could not load OCR rows.");
      } finally {
        setOcrRowsLoading(false);
      }
    },
    [ocrRowsOffset, ocrRowsQuery, selectedOcrTaskId],
  );

  const loadReturnTasks = useCallback(
    async ({ bypassCache = false } = {}) => {
      setReturnTasksLoading(true);
      setReturnTasksError("");
      try {
        const data = await fetchAdminReturnTasks({
          query: returnAppliedQuery,
          limit: RETURN_TASKS_PAGE_SIZE,
          offset: returnTasksOffset,
          bypassCache,
        });
        setReturnTasks(data.tasks);
        setReturnTasksTotal(data.total);
        if (data.tasks.length && !selectedReturnTaskId) {
          setSelectedReturnTaskId(data.tasks[0].task_id || "");
        }
      } catch (err) {
        setReturnTasks([]);
        setReturnTasksTotal(0);
        setReturnTasksError(err instanceof Error ? err.message : "Could not load return analysis tasks.");
      } finally {
        setReturnTasksLoading(false);
      }
    },
    [returnAppliedQuery, returnTasksOffset, selectedReturnTaskId],
  );

  const loadReturnRows = useCallback(
    async ({ bypassCache = false } = {}) => {
      if (!selectedReturnTaskId) {
        setReturnRows([]);
        setReturnRowsTotal(0);
        return;
      }
      setReturnRowsLoading(true);
      setReturnRowsError("");
      try {
        const data = await fetchAdminReturnTaskRows({
          taskId: selectedReturnTaskId,
          query: returnRowsQuery.trim(),
          limit: RETURN_ROWS_PAGE_SIZE,
          offset: returnRowsOffset,
          bypassCache,
        });
        setReturnRows(data.rows);
        setReturnRowsTotal(data.total);
      } catch (err) {
        setReturnRows([]);
        setReturnRowsTotal(0);
        setReturnRowsError(err instanceof Error ? err.message : "Could not load return analysis rows.");
      } finally {
        setReturnRowsLoading(false);
      }
    },
    [returnRowsOffset, returnRowsQuery, selectedReturnTaskId],
  );

  const loadAdminJobs = useCallback(
    async ({ bypassCache = false } = {}) => {
      setAdminJobsLoading(true);
      setAdminJobsError("");
      try {
        const data = await fetchAdminJobs({
          limit: ADMIN_JOBS_PAGE_SIZE,
          offset: adminJobsOffset,
          bypassCache,
        });
        setAdminJobs(data.jobs);
        setAdminJobsTotal(data.total);
      } catch (err) {
        setAdminJobs([]);
        setAdminJobsTotal(0);
        setAdminJobsError(err instanceof Error ? err.message : "Could not load admin jobs.");
      } finally {
        setAdminJobsLoading(false);
      }
    },
    [adminJobsOffset],
  );

  const loadWalletAudit = useCallback(
    async ({ bypassCache = false } = {}) => {
      setWalletAuditLoading(true);
      setWalletAuditError("");
      try {
        const data = await fetchAdminWalletAudit({
          query: walletAuditAppliedQuery,
          limit: WALLET_AUDIT_PAGE_SIZE,
          offset: walletAuditOffset,
          bypassCache,
        });
        setWalletAuditEvents(data.events);
        setWalletAuditTotal(data.total);
      } catch (err) {
        setWalletAuditEvents([]);
        setWalletAuditTotal(0);
        setWalletAuditError(err instanceof Error ? err.message : "Could not load wallet audit.");
      } finally {
        setWalletAuditLoading(false);
      }
    },
    [walletAuditAppliedQuery, walletAuditOffset],
  );

  useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    loadAudit();
  }, [loadAudit]);

  useEffect(() => {
    loadOcrTasks();
  }, [loadOcrTasks]);

  useEffect(() => {
    loadOcrRows();
  }, [loadOcrRows]);

  useEffect(() => {
    loadReturnTasks();
  }, [loadReturnTasks]);

  useEffect(() => {
    loadReturnRows();
  }, [loadReturnRows]);

  useEffect(() => {
    loadAdminJobs();
  }, [loadAdminJobs]);

  useEffect(() => {
    loadWalletAudit();
  }, [loadWalletAudit]);

  useEffect(() => {
    setSelectedUserIds((prev) => prev.filter((id) => users.some((u) => u.id === id)));
  }, [users]);

  useEffect(() => {
    try {
      localStorage.setItem(
        ADMIN_UI_PREFS_KEY,
        JSON.stringify({
          usersViewMode,
          usersSort,
          auditViewMode,
          csvColumns,
        }),
      );
    } catch {
      // Ignore localStorage write issues.
    }
  }, [auditViewMode, csvColumns, usersSort, usersViewMode]);

  const handleApplySearch = useCallback(() => {
    setCursor(null);
    setCursorHistory([]);
    setCursorPage(1);
    setInfiniteCursor(null);
    setInfiniteHasMore(false);
    setAppliedQuery(searchInput.trim());
  }, [searchInput]);

  const handleSearchKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleApplySearch();
      }
    },
    [handleApplySearch],
  );

  const handleToggleRole = useCallback(
    async (row) => {
      if (!row || pendingUserId || pendingBulk) return;
      const nextIsAdmin = !row.is_admin;
      setPendingUserId(row.id);
      setRoleError("");
      const previous = users;
      setUsers((current) =>
        current.map((u) => (u.id === row.id ? { ...u, is_admin: nextIsAdmin } : u)),
      );
      try {
        const updated = await updateAdminUserRole(row.id, nextIsAdmin);
        setUsers((current) =>
          current.map((u) => (u.id === row.id ? { ...u, ...(updated || {}) } : u)),
        );
        loadAudit({ bypassCache: true });
      } catch (err) {
        setUsers(previous);
        setRoleError(err instanceof Error ? err.message : "Could not update user role.");
      } finally {
        setPendingUserId(null);
      }
    },
    [loadAudit, pendingBulk, pendingUserId, users],
  );

  const handleBulkRoleChange = useCallback(
    async (nextIsAdmin) => {
      if (!selectedUserIds.length || pendingUserId || pendingBulk) return;
      const targetIds = [...selectedUserIds];
      setPendingBulk(true);
      setRoleError("");
      const previous = users;
      setUsers((current) =>
        current.map((u) =>
          targetIds.includes(u.id) ? { ...u, is_admin: Boolean(nextIsAdmin) } : u,
        ),
      );
      try {
        await updateAdminUsersRoleBulk(targetIds, Boolean(nextIsAdmin));
        await loadUsers({ bypassCache: true });
        await loadAudit({ bypassCache: true });
        setSelectedUserIds([]);
      } catch (err) {
        setUsers(previous);
        setRoleError(err instanceof Error ? err.message : "Could not run bulk role update.");
      } finally {
        setPendingBulk(false);
      }
    },
    [loadAudit, loadUsers, pendingBulk, pendingUserId, selectedUserIds, users],
  );

  const handleWalletCredit = useCallback(
    async ({ targetUserId = null, targetEmail = "", amount = 0, note = "" } = {}) => {
      setWalletCreditPending(true);
      setWalletCreditError("");
      setWalletCreditSuccess("");
      try {
        const cleanAmount = Number(amount || 0);
        const cleanTargetEmail = String(targetEmail || "").trim();
        const cleanTargetUserId =
          targetUserId !== null && targetUserId !== undefined ? Number(targetUserId) : null;
        await adminCreditUserWallet({
          targetUserId: Number.isFinite(cleanTargetUserId) ? cleanTargetUserId : null,
          targetEmail: cleanTargetEmail,
          amount: cleanAmount,
          note,
        });
        await loadUsers({ bypassCache: true });
        await loadWalletAudit({ bypassCache: true });
        const targetLabel = cleanTargetEmail || `user #${cleanTargetUserId}`;
        setWalletCreditSuccess(
          `Added ${cleanAmount} coin${cleanAmount === 1 ? "" : "s"} to ${targetLabel}.`,
        );
      } catch (err) {
        setWalletCreditError(err instanceof Error ? err.message : "Could not add wallet coins.");
      } finally {
        setWalletCreditPending(false);
      }
    },
    [loadUsers, loadWalletAudit],
  );

  const handleDownloadUserMasterData = useCallback(async (row, platform = "") => {
    const userId = Number(row?.id || 0);
    if (!Number.isFinite(userId) || userId <= 0) return;
    const cleanPlatform = String(platform || "").trim().toLowerCase();
    setMasterDataError("");
    if (cleanPlatform) {
      setDownloadingMasterPlatformKey(`${userId}:${cleanPlatform}`);
    } else {
      setDownloadingMasterUserId(userId);
    }
    try {
      const blob = await downloadAdminUserMasterCsv(userId, cleanPlatform);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const safeEmail = String(row?.email || "").replace(/[^a-zA-Z0-9._-]+/g, "_");
      const platformSuffix = cleanPlatform ? `_${cleanPlatform}` : "";
      const fallbackPlatformSuffix = cleanPlatform ? `-${cleanPlatform}` : "";
      a.download = safeEmail
        ? `${safeEmail}${platformSuffix}_master_orders.csv`
        : `user-${userId}${fallbackPlatformSuffix}-master-orders.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      const platformLabel = cleanPlatform ? `${PLATFORM_LABELS[cleanPlatform] || cleanPlatform} ` : "";
      setMasterDataError(
        err instanceof Error ? err.message : `Could not download ${platformLabel}master CSV.`,
      );
    } finally {
      if (cleanPlatform) {
        setDownloadingMasterPlatformKey("");
      } else {
        setDownloadingMasterUserId(null);
      }
    }
  }, []);

  const handleDownloadUserSuspiciousData = useCallback(async (row, platform = "") => {
    const userId = Number(row?.id || 0);
    if (!Number.isFinite(userId) || userId <= 0) return;
    const cleanPlatform = String(platform || "").trim().toLowerCase();
    setSuspiciousDataError("");
    if (cleanPlatform) {
      setDownloadingSuspiciousPlatformKey(`${userId}:${cleanPlatform}`);
    } else {
      setDownloadingSuspiciousUserId(userId);
    }
    try {
      const blob = await downloadAdminUserSuspiciousCsv(userId, cleanPlatform);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const safeEmail = String(row?.email || "").replace(/[^a-zA-Z0-9._-]+/g, "_");
      const platformSuffix = cleanPlatform ? `_${cleanPlatform}` : "";
      const fallbackPlatformSuffix = cleanPlatform ? `-${cleanPlatform}` : "";
      a.download = safeEmail
        ? `${safeEmail}${platformSuffix}_suspicious_customers.csv`
        : `user-${userId}${fallbackPlatformSuffix}-suspicious-customers.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      const platformLabel = cleanPlatform ? `${PLATFORM_LABELS[cleanPlatform] || cleanPlatform} ` : "";
      setSuspiciousDataError(
        err instanceof Error ? err.message : `Could not download ${platformLabel}suspicious CSV.`,
      );
    } finally {
      if (cleanPlatform) {
        setDownloadingSuspiciousPlatformKey("");
      } else {
        setDownloadingSuspiciousUserId(null);
      }
    }
  }, []);

  const summaryText = useMemo(() => {
    if (!usersTotal) return "No users found";
    if (usersViewMode === "infinite") {
      return `Loaded ${users.length} of ${usersTotal} users`;
    }
    const start = (cursorPage - 1) * USERS_PAGE_SIZE + 1;
    const end = Math.min(start + users.length - 1, usersTotal);
    return `Showing ${start}-${end} of ${usersTotal} users`;
  }, [cursorPage, users.length, usersTotal, usersViewMode]);

  const inputStyle = {
    borderRadius: 10,
    border: `1px solid ${brand.border}`,
    background: brand.bgInput,
    color: brand.text,
    fontFamily: font,
    fontSize: 13,
    padding: "10px 12px",
    outline: "none",
  };

  return (
    <div style={{ minHeight: "calc(100vh - 64px)", background: brand.bgPage, padding: "24px 20px 30px" }}>
      <div style={{ maxWidth: 1060, margin: "0 auto", display: "grid", gap: 14 }}>
        <div
          style={{
            borderRadius: 16,
            border: `1px solid ${brand.border}`,
            background: brand.bgCard,
            padding: 16,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          <div>
            <h1 style={{ margin: 0, color: brand.text, fontFamily: font, fontSize: 26, fontWeight: 800 }}>
              Admin Dashboard
            </h1>
            <p style={{ margin: "8px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
              High-level system metrics for users and crop pipeline health.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              loadMetrics();
            }}
            disabled={metricsLoading}
            style={{
              borderRadius: 10,
              border: "none",
              background: metricsLoading ? brand.textDim : brand.gradientCta,
              color: "#fff",
              fontFamily: font,
              fontSize: 13,
              fontWeight: 700,
              padding: "9px 14px",
              cursor: metricsLoading ? "not-allowed" : "pointer",
            }}
          >
            {metricsLoading ? "Refreshing..." : "Refresh"}
          </button>
        </div>

        {metricsLoading ? (
          <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>Loading metrics...</div>
        ) : metricsError ? (
          <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{metricsError}</div>
        ) : metrics ? (
          <div
            style={{
              borderRadius: 16,
              border: `1px solid ${brand.border}`,
              background: brand.bgCard,
              padding: 14,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: 10,
            }}
          >
            <StatCard label="Total users" value={metrics.total_users ?? 0} />
            <StatCard label="Total jobs" value={metrics.total_jobs ?? 0} />
            <StatCard label="Successful jobs" value={metrics.total_success ?? 0} />
            <StatCard label="Failed jobs" value={metrics.total_failed ?? 0} />
            <StatCard label="Jobs today" value={metrics.jobs_today ?? 0} />
            <StatCard label="Active users (7d)" value={metrics.active_users_7d ?? 0} />
            <StatCard
              label="Manual high-risk customers"
              value={metrics.manual_high_risk_customers_total ?? 0}
              hint={`Suborders: ${metrics.manual_high_risk_suborders_total ?? 0}`}
            />
            <StatCard
              label="Manual high-risk added (7d)"
              value={metrics.manual_high_risk_customers_7d ?? 0}
              hint={`Suborders (7d): ${metrics.manual_high_risk_suborders_7d ?? 0}`}
            />
          </div>
        ) : (
          <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>No metrics available.</div>
        )}

        <UsersSection
          searchInput={searchInput}
          setSearchInput={setSearchInput}
          appliedQuery={appliedQuery}
          setAppliedQuery={setAppliedQuery}
          handleApplySearch={handleApplySearch}
          handleSearchKeyDown={handleSearchKeyDown}
          loadUsers={loadUsers}
          users={users}
          usersLoading={usersLoading}
          usersError={usersError}
          summaryText={summaryText}
          cursorPage={cursorPage}
          totalPages={totalPages}
          setCursorPage={setCursorPage}
          cursor={cursor}
          setCursor={setCursor}
          cursorHistory={cursorHistory}
          setCursorHistory={setCursorHistory}
          nextCursor={nextCursor}
          usersViewMode={usersViewMode}
          setUsersViewMode={setUsersViewMode}
          usersSort={usersSort}
          setUsersSort={setUsersSort}
          infiniteHasMore={infiniteHasMore}
          infiniteLoadingMore={infiniteLoadingMore}
          loadMoreUsers={loadMoreUsers}
          selectedUserIds={selectedUserIds}
          setSelectedUserIds={setSelectedUserIds}
          pendingUserId={pendingUserId}
          pendingBulk={pendingBulk}
          handleToggleRole={handleToggleRole}
          handleBulkRoleChange={handleBulkRoleChange}
          roleError={roleError}
          walletCreditPending={walletCreditPending}
          walletCreditError={walletCreditError}
          walletCreditSuccess={walletCreditSuccess}
          handleWalletCredit={handleWalletCredit}
          masterDataError={masterDataError}
          suspiciousDataError={suspiciousDataError}
          downloadingMasterUserId={downloadingMasterUserId}
          downloadingMasterPlatformKey={downloadingMasterPlatformKey}
          downloadingSuspiciousUserId={downloadingSuspiciousUserId}
          downloadingSuspiciousPlatformKey={downloadingSuspiciousPlatformKey}
          handleDownloadUserMasterData={handleDownloadUserMasterData}
          handleDownloadUserSuspiciousData={handleDownloadUserSuspiciousData}
          currentUserEmail={currentUserEmail}
          inputStyle={inputStyle}
        />

        <WalletAuditSection
          inputStyle={inputStyle}
          events={walletAuditEvents}
          total={walletAuditTotal}
          page={walletAuditPage}
          totalPages={walletAuditTotalPages}
          setPage={setWalletAuditPage}
          loading={walletAuditLoading}
          error={walletAuditError}
          query={walletAuditQuery}
          setQuery={setWalletAuditQuery}
          onApplyQuery={() => {
            setWalletAuditAppliedQuery(walletAuditQuery.trim());
            setWalletAuditPage(1);
          }}
          onResetQuery={() => {
            setWalletAuditQuery("");
            setWalletAuditAppliedQuery("");
            setWalletAuditPage(1);
          }}
          onRefresh={() => loadWalletAudit({ bypassCache: true })}
        />

        <AuditSection
          inputStyle={inputStyle}
          events={auditEvents}
          total={auditTotal}
          page={auditPage}
          totalPages={auditTotalPages}
          setPage={setAuditPage}
          viewMode={auditViewMode}
          setViewMode={setAuditViewMode}
          loadingMore={auditInfiniteLoadingMore}
          hasMore={auditInfiniteHasMore}
          onLoadMore={loadMoreAudit}
          loading={auditLoading}
          error={auditError}
          actorFilter={auditActorFilter}
          setActorFilter={setAuditActorFilter}
          targetFilter={auditTargetFilter}
          setTargetFilter={setAuditTargetFilter}
          fromDate={auditFromDate}
          setFromDate={setAuditFromDate}
          toDate={auditToDate}
          setToDate={setAuditToDate}
          onApplyFilters={() => {
            setAuditAppliedFilters({
              actor: auditActorFilter.trim(),
              target: auditTargetFilter.trim(),
              from: auditFromDate,
              to: auditToDate,
            });
            setAuditInfiniteCursor(null);
            setAuditInfiniteHasMore(false);
            setAuditPage(1);
          }}
          onResetFilters={() => {
            setAuditActorFilter("");
            setAuditTargetFilter("");
            setAuditFromDate("");
            setAuditToDate("");
            setAuditAppliedFilters({ actor: "", target: "", from: "", to: "" });
            setAuditInfiniteCursor(null);
            setAuditInfiniteHasMore(false);
            setAuditPage(1);
          }}
          onExportCsv={async () => {
            if (!csvColumns.length) return;
            const blob = await exportAdminRoleAuditCsv({
              actorQuery: auditAppliedFilters.actor,
              targetQuery: auditAppliedFilters.target,
              fromDate: auditAppliedFilters.from
                ? `${auditAppliedFilters.from}T00:00:00.000Z`
                : "",
              toDate: auditAppliedFilters.to ? `${auditAppliedFilters.to}T23:59:59.999Z` : "",
              columns: csvColumns,
            });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "admin-role-audit.csv";
            a.click();
            URL.revokeObjectURL(url);
          }}
          csvColumns={csvColumns}
          setCsvColumns={setCsvColumns}
          onPresetDateRange={(days) => {
            const now = new Date();
            const to = dateInputValue(now);
            const fromDateObj = new Date(now);
            fromDateObj.setDate(now.getDate() - Math.max(0, days - 1));
            const from = dateInputValue(fromDateObj);
            setAuditFromDate(from);
            setAuditToDate(to);
            setAuditAppliedFilters({
              actor: auditActorFilter.trim(),
              target: auditTargetFilter.trim(),
              from,
              to,
            });
            setAuditInfiniteCursor(null);
            setAuditInfiniteHasMore(false);
            setAuditPage(1);
          }}
          onRefresh={() => loadAudit({ bypassCache: true })}
        />

        <AdminOcrSection
          inputStyle={inputStyle}
          tasks={ocrTasks}
          tasksTotal={ocrTasksTotal}
          tasksPage={ocrTasksPage}
          setTasksPage={setOcrTasksPage}
          tasksLoading={ocrTasksLoading}
          tasksError={ocrTasksError}
          ocrQuery={ocrQuery}
          setOcrQuery={setOcrQuery}
          onApplyTaskSearch={() => {
            setOcrAppliedQuery(ocrQuery.trim());
            setOcrTasksPage(1);
          }}
          onRefreshTasks={() => loadOcrTasks({ bypassCache: true })}
          selectedTaskId={selectedOcrTaskId}
          setSelectedTaskId={(taskId) => {
            setSelectedOcrTaskId(taskId);
            setOcrRowsPage(1);
          }}
          rows={ocrRows}
          rowsTotal={ocrRowsTotal}
          rowsPage={ocrRowsPage}
          setRowsPage={setOcrRowsPage}
          rowsLoading={ocrRowsLoading}
          rowsError={ocrRowsError}
          rowsQuery={ocrRowsQuery}
          setRowsQuery={setOcrRowsQuery}
          onApplyRowsSearch={() => setOcrRowsPage(1)}
          onRefreshRows={() => loadOcrRows({ bypassCache: true })}
        />

        <AdminReturnSection
          inputStyle={inputStyle}
          tasks={returnTasks}
          tasksTotal={returnTasksTotal}
          tasksPage={returnTasksPage}
          setTasksPage={setReturnTasksPage}
          tasksLoading={returnTasksLoading}
          tasksError={returnTasksError}
          returnQuery={returnQuery}
          setReturnQuery={setReturnQuery}
          onApplyTaskSearch={() => {
            setReturnAppliedQuery(returnQuery.trim());
            setReturnTasksPage(1);
          }}
          onRefreshTasks={() => loadReturnTasks({ bypassCache: true })}
          selectedTaskId={selectedReturnTaskId}
          setSelectedTaskId={(taskId) => {
            setSelectedReturnTaskId(taskId);
            setReturnRowsPage(1);
          }}
          rows={returnRows}
          rowsTotal={returnRowsTotal}
          rowsPage={returnRowsPage}
          setRowsPage={setReturnRowsPage}
          rowsLoading={returnRowsLoading}
          rowsError={returnRowsError}
          rowsQuery={returnRowsQuery}
          setRowsQuery={setReturnRowsQuery}
          onApplyRowsSearch={() => setReturnRowsPage(1)}
          onRefreshRows={() => loadReturnRows({ bypassCache: true })}
        />

        <AdminJobsSplitSection
          inputStyle={inputStyle}
          jobs={adminJobs}
          total={adminJobsTotal}
          page={adminJobsPage}
          setPage={setAdminJobsPage}
          loading={adminJobsLoading}
          error={adminJobsError}
          onRefresh={() => loadAdminJobs({ bypassCache: true })}
        />
      </div>
    </div>
  );
}

function UsersSection({
  searchInput,
  setSearchInput,
  appliedQuery,
  setAppliedQuery,
  handleApplySearch,
  handleSearchKeyDown,
  loadUsers,
  users,
  usersLoading,
  usersError,
  summaryText,
  cursorPage,
  totalPages,
  setCursorPage,
  cursor,
  setCursor,
  cursorHistory,
  setCursorHistory,
  nextCursor,
  usersViewMode,
  setUsersViewMode,
  usersSort,
  setUsersSort,
  infiniteHasMore,
  infiniteLoadingMore,
  loadMoreUsers,
  selectedUserIds,
  setSelectedUserIds,
  pendingUserId,
  pendingBulk,
  handleToggleRole,
  handleBulkRoleChange,
  roleError,
  walletCreditPending,
  walletCreditError,
  walletCreditSuccess,
  handleWalletCredit,
  masterDataError,
  suspiciousDataError,
  downloadingMasterUserId,
  downloadingMasterPlatformKey,
  downloadingSuspiciousUserId,
  downloadingSuspiciousPlatformKey,
  handleDownloadUserMasterData,
  handleDownloadUserSuspiciousData,
  currentUserEmail,
  inputStyle,
}) {
  const isInfinite = usersViewMode === "infinite";
  const [creditTarget, setCreditTarget] = useState("");
  const [creditAmount, setCreditAmount] = useState("");
  const [creditNote, setCreditNote] = useState("");
  const selectedUsers = useMemo(
    () => users.filter((row) => selectedUserIds.includes(row.id)),
    [selectedUserIds, users],
  );
  const singleSelectedUser = selectedUsers.length === 1 ? selectedUsers[0] : null;

  useEffect(() => {
    if (!singleSelectedUser) return;
    setCreditTarget(singleSelectedUser.email || String(singleSelectedUser.id));
  }, [singleSelectedUser?.email, singleSelectedUser?.id]);

  const submitCredit = async () => {
    const target = String(creditTarget || "").trim();
    const amount = Number(creditAmount || 0);
    if (!target || !Number.isFinite(amount) || amount <= 0 || walletCreditPending) return;
    const parsedId = Number(target);
    const useId = Number.isInteger(parsedId) && parsedId > 0 && /^\d+$/.test(target);
    await handleWalletCredit({
      targetUserId: useId ? parsedId : null,
      targetEmail: useId ? "" : target,
      amount,
      note: creditNote.trim(),
    });
    setCreditAmount("");
    setCreditNote("");
  };

  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${brand.border}`,
        background: brand.bgCard,
        padding: 16,
        display: "grid",
        gap: 14,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2 style={{ margin: 0, color: brand.text, fontFamily: font, fontSize: 20, fontWeight: 800 }}>
            User management
          </h2>
          <p style={{ margin: "6px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
            Search by name or email, then toggle admin access. The last admin can&apos;t be demoted.
          </p>
        </div>
        <button
          type="button"
          onClick={() => loadUsers({ bypassCache: true })}
          disabled={usersLoading}
          style={{
            borderRadius: 10,
            border: `1px solid ${brand.border}`,
            background: usersLoading ? "rgba(255,255,255,0.04)" : "rgba(255,255,255,0.06)",
            color: brand.text,
            fontFamily: font,
            fontSize: 12.5,
            fontWeight: 700,
            padding: "8px 12px",
            cursor: usersLoading ? "not-allowed" : "pointer",
          }}
        >
          {usersLoading ? "Refreshing..." : "Refresh"}
        </button>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1fr) auto auto",
          gap: 10,
          alignItems: "center",
        }}
      >
        <input
          type="search"
          value={searchInput}
          placeholder="Search by name or email"
          aria-label="Search users by name or email"
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={handleSearchKeyDown}
          style={inputStyle}
        />
        <button
          type="button"
          onClick={handleApplySearch}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: brand.gradientCta,
            color: "#fff",
            border: "none",
            fontWeight: 700,
            padding: "10px 16px",
          }}
        >
          Search
        </button>
        <button
          type="button"
          onClick={() => {
            setSearchInput("");
            if (appliedQuery) {
              setCursor(null);
              setCursorHistory([]);
              setCursorPage(1);
              setUsersViewMode("paged");
              setAppliedQuery("");
            }
          }}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.04)",
            padding: "10px 14px",
          }}
        >
          Clear
        </button>
      </div>

      {roleError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 12.5 }}>{roleError}</div>
      ) : null}
      {walletCreditError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 12.5 }}>{walletCreditError}</div>
      ) : null}
      {walletCreditSuccess ? (
        <div style={{ color: "#86efac", fontFamily: font, fontSize: 12.5 }}>{walletCreditSuccess}</div>
      ) : null}
      {masterDataError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 12.5 }}>{masterDataError}</div>
      ) : null}
      {suspiciousDataError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 12.5 }}>{suspiciousDataError}</div>
      ) : null}

      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div style={{ display: "inline-flex", border: `1px solid ${brand.border}`, borderRadius: 10, overflow: "hidden" }}>
          <button
            type="button"
            onClick={() => {
              if (usersViewMode === "paged") return;
              setCursor(null);
              setCursorHistory([]);
              setCursorPage(1);
              setUsersViewMode("paged");
            }}
            style={{
              ...inputStyle,
              border: "none",
              borderRight: `1px solid ${brand.border}`,
              borderRadius: 0,
              padding: "7px 10px",
              cursor: "pointer",
              background: usersViewMode === "paged" ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.04)",
            }}
          >
            Paged
          </button>
          <button
            type="button"
            onClick={() => {
              if (usersViewMode === "infinite") return;
              setCursor(null);
              setCursorHistory([]);
              setCursorPage(1);
              setUsersViewMode("infinite");
            }}
            style={{
              ...inputStyle,
              border: "none",
              borderRadius: 0,
              padding: "7px 10px",
              cursor: "pointer",
              background: usersViewMode === "infinite" ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.04)",
            }}
          >
            Infinite
          </button>
        </div>
        <select
          value={usersSort}
          onChange={(e) => setUsersSort(e.target.value)}
          style={{
            ...inputStyle,
            padding: "7px 10px",
            background: "rgba(15,23,42,0.88)",
            color: brand.text,
            border: `1px solid ${brand.border}`,
          }}
          aria-label="Sort users"
        >
          <option value="default" style={{ color: "#111827", background: "#ffffff" }}>
            Sort: Default
          </option>
          <option value="labels_desc" style={{ color: "#111827", background: "#ffffff" }}>
            Sort: Labels highest to lowest
          </option>
          <option value="labels_asc" style={{ color: "#111827", background: "#ffffff" }}>
            Sort: Labels lowest to highest
          </option>
          <option value="risky_desc" style={{ color: "#111827", background: "#ffffff" }}>
            Sort: Risky highest to lowest
          </option>
          <option value="risky_asc" style={{ color: "#111827", background: "#ffffff" }}>
            Sort: Risky lowest to highest
          </option>
        </select>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
          Selected: {selectedUserIds.length}
        </div>
        <button
          type="button"
          disabled={!selectedUserIds.length || pendingBulk || pendingUserId !== null}
          onClick={() => handleBulkRoleChange(true)}
          style={{
            ...inputStyle,
            padding: "7px 12px",
            cursor:
              !selectedUserIds.length || pendingBulk || pendingUserId !== null
                ? "not-allowed"
                : "pointer",
            background: brand.gradientCta,
            border: "none",
            color: "#fff",
            fontWeight: 700,
            opacity: !selectedUserIds.length ? 0.6 : 1,
          }}
        >
          {pendingBulk ? "Applying..." : "Make selected admin"}
        </button>
        <button
          type="button"
          disabled={!selectedUserIds.length || pendingBulk || pendingUserId !== null}
          onClick={() => handleBulkRoleChange(false)}
          style={{
            ...inputStyle,
            padding: "7px 12px",
            cursor:
              !selectedUserIds.length || pendingBulk || pendingUserId !== null
                ? "not-allowed"
                : "pointer",
            background: "rgba(127, 29, 29, 0.35)",
            border: "1px solid rgba(248, 113, 113, 0.45)",
            color: "#fff",
            fontWeight: 700,
            opacity: !selectedUserIds.length ? 0.6 : 1,
          }}
        >
          {pendingBulk ? "Applying..." : "Remove selected admin"}
        </button>
      </div>

      <div
        style={{
          border: `1px solid ${brand.border}`,
          borderRadius: 12,
          background: "rgba(255,255,255,0.02)",
          padding: 12,
          display: "grid",
          gap: 10,
        }}
      >
        <div style={{ color: brand.text, fontFamily: font, fontSize: 13.5, fontWeight: 700 }}>
          Add wallet coins (admin only)
        </div>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
          Target by user id or email. Selecting exactly one user auto-fills this field.
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(180px, 1fr) 110px minmax(200px, 1fr) auto",
            gap: 8,
            alignItems: "center",
          }}
        >
          <input
            type="text"
            value={creditTarget}
            onChange={(e) => setCreditTarget(e.target.value)}
            placeholder="Target user id or email"
            style={inputStyle}
          />
          <input
            type="number"
            min={1}
            step={1}
            value={creditAmount}
            onChange={(e) => setCreditAmount(e.target.value)}
            placeholder="Coins"
            style={inputStyle}
          />
          <input
            type="text"
            value={creditNote}
            onChange={(e) => setCreditNote(e.target.value)}
            placeholder="Optional note"
            style={inputStyle}
          />
          <button
            type="button"
            onClick={submitCredit}
            disabled={walletCreditPending}
            style={{
              ...inputStyle,
              border: "none",
              background: brand.gradientCta,
              color: "#fff",
              fontWeight: 700,
              cursor: walletCreditPending ? "not-allowed" : "pointer",
              padding: "10px 12px",
            }}
          >
            {walletCreditPending ? "Adding..." : "Add coins"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>{summaryText}</div>
        {isInfinite ? (
          <div style={{ color: brand.textDim, fontFamily: font, fontSize: 12 }}>
            Scroll table to load more users automatically.
          </div>
        ) : (
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            disabled={cursorPage <= 1 || usersLoading}
            onClick={() => {
              if (cursorHistory.length === 0) return;
              const nextHistory = [...cursorHistory];
              const prevCursor = nextHistory.pop() ?? null;
              setCursorHistory(nextHistory);
              setCursor(prevCursor);
              setCursorPage((p) => Math.max(1, p - 1));
            }}
            style={{
              ...inputStyle,
              padding: "7px 10px",
              cursor: cursorPage <= 1 || usersLoading ? "not-allowed" : "pointer",
              opacity: cursorPage <= 1 ? 0.6 : 1,
            }}
          >
            Prev
          </button>
          <span style={{ color: brand.text, fontFamily: font, fontSize: 13, alignSelf: "center" }}>
            Page {cursorPage}/{totalPages}
          </span>
          <button
            type="button"
            disabled={!nextCursor || usersLoading}
            onClick={() => {
              if (!nextCursor) return;
              setCursorHistory((prev) => [...prev, cursor]);
              setCursor(nextCursor);
              setCursorPage((p) => p + 1);
            }}
            style={{
              ...inputStyle,
              padding: "7px 10px",
              cursor: !nextCursor || usersLoading ? "not-allowed" : "pointer",
              opacity: !nextCursor ? 0.6 : 1,
            }}
          >
            Next
          </button>
        </div>
        )}
      </div>

      {usersLoading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>Loading users...</div>
      ) : usersError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{usersError}</div>
      ) : users.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
          No users match the current search.
        </div>
      ) : (
        <UsersTable
          users={users}
          selectedUserIds={selectedUserIds}
          setSelectedUserIds={setSelectedUserIds}
          pendingUserId={pendingUserId}
          pendingBulk={pendingBulk}
          handleToggleRole={handleToggleRole}
          downloadingMasterUserId={downloadingMasterUserId}
          downloadingMasterPlatformKey={downloadingMasterPlatformKey}
          downloadingSuspiciousUserId={downloadingSuspiciousUserId}
          downloadingSuspiciousPlatformKey={downloadingSuspiciousPlatformKey}
          handleDownloadUserMasterData={handleDownloadUserMasterData}
          handleDownloadUserSuspiciousData={handleDownloadUserSuspiciousData}
          currentUserEmail={currentUserEmail}
          onReachBottom={isInfinite ? loadMoreUsers : null}
        />
      )}
      {isInfinite && users.length > 0 ? (
        <div style={{ display: "flex", justifyContent: "center" }}>
          {infiniteLoadingMore ? (
            <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>Loading more users...</div>
          ) : infiniteHasMore ? (
            <button
              type="button"
              onClick={loadMoreUsers}
              style={{
                ...inputStyle,
                cursor: "pointer",
                padding: "8px 12px",
                background: "rgba(255,255,255,0.06)",
              }}
            >
              Load more
            </button>
          ) : (
            <div style={{ color: brand.textDim, fontFamily: font, fontSize: 12 }}>All users loaded.</div>
          )}
        </div>
      ) : null}
    </div>
  );
}

const USER_TABLE_MIN_WIDTH = 1620;
const USER_TABLE_GRID_COLUMNS =
  "36px minmax(130px, 1.1fr) minmax(200px, 1.8fr) 80px 72px 110px 110px 150px 560px";
const USER_TABLE_COLUMN_GAP = 10;
const USER_TABLE_ROW_PADDING = "10px 12px";
const USER_TABLE_HEADER_BG = "rgba(15, 23, 42, 0.96)";

function UsersTable({
  users,
  selectedUserIds,
  setSelectedUserIds,
  pendingUserId,
  pendingBulk,
  handleToggleRole,
  downloadingMasterUserId,
  downloadingMasterPlatformKey,
  downloadingSuspiciousUserId,
  downloadingSuspiciousPlatformKey,
  handleDownloadUserMasterData,
  handleDownloadUserSuspiciousData,
  currentUserEmail,
  onReachBottom,
}) {
  const [scrollTop, setScrollTop] = useState(0);
  const selectedSet = useMemo(() => new Set(selectedUserIds), [selectedUserIds]);
  const allSelected = users.length > 0 && users.every((u) => selectedSet.has(u.id));
  const startIndex = Math.max(0, Math.floor(scrollTop / USER_ROW_HEIGHT) - 4);
  const visibleCount = Math.ceil(USER_TABLE_HEIGHT / USER_ROW_HEIGHT) + 8;
  const endIndex = Math.min(users.length, startIndex + visibleCount);
  const visibleRows = users.slice(startIndex, endIndex);
  const topPad = startIndex * USER_ROW_HEIGHT;
  const bottomPad = Math.max(0, (users.length - endIndex) * USER_ROW_HEIGHT);

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedUserIds([]);
      return;
    }
    setSelectedUserIds(users.map((u) => u.id));
  };

  const toggleSingle = (userId) => {
    setSelectedUserIds((prev) =>
      prev.includes(userId) ? prev.filter((id) => id !== userId) : [...prev, userId],
    );
  };

  const rowGridStyle = {
    display: "grid",
    gridTemplateColumns: USER_TABLE_GRID_COLUMNS,
    minWidth: USER_TABLE_MIN_WIDTH,
    columnGap: USER_TABLE_COLUMN_GAP,
    alignItems: "center",
    padding: USER_TABLE_ROW_PADDING,
    boxSizing: "border-box",
  };

  return (
    <div
      style={{
        border: `1px solid ${brand.border}`,
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          height: USER_TABLE_HEIGHT,
          overflow: "auto",
          position: "relative",
        }}
        onScroll={(e) => {
          const el = e.currentTarget;
          setScrollTop(el.scrollTop);
          if (onReachBottom && el.scrollTop + el.clientHeight >= el.scrollHeight - USER_ROW_HEIGHT * 1.5) {
            onReachBottom();
          }
        }}
      >
        <div
          style={{
            ...rowGridStyle,
            position: "sticky",
            top: 0,
            zIndex: 2,
            background: USER_TABLE_HEADER_BG,
            borderBottom: `1px solid ${brand.border}`,
            color: brand.textMuted,
            fontFamily: font,
            fontSize: 11.5,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            alignItems: "center",
          }}
        >
          <label style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
            <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
          </label>
          <span>Name</span>
          <span>Email</span>
          <span style={{ textAlign: "right" }}>Labels</span>
          <span style={{ textAlign: "right" }}>Risky</span>
          <span>Master data</span>
          <span>Suspicious data</span>
          <span>Created</span>
          <span style={{ textAlign: "right" }}>Role</span>
        </div>
        <div style={{ height: topPad }} />
        {visibleRows.map((row) => {
          const isSelf = currentUserEmail && row.email && row.email.toLowerCase() === currentUserEmail;
          const pending = pendingUserId === row.id;
          const buttonLabel = pending
            ? "Updating..."
            : row.is_admin
              ? "Remove admin"
              : "Make admin";
          return (
            <div
              key={row.id}
              style={{
                ...rowGridStyle,
                borderTop: `1px solid ${brand.border}`,
                background: row.is_admin ? "rgba(167, 139, 250, 0.06)" : "transparent",
                minHeight: USER_ROW_HEIGHT,
              }}
            >
              <label style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
                <input
                  type="checkbox"
                  checked={selectedSet.has(row.id)}
                  onChange={() => toggleSingle(row.id)}
                />
              </label>
              <div
                style={{
                  color: brand.text,
                  fontFamily: font,
                  fontSize: 13,
                  fontWeight: 600,
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={row.name || ""}
              >
                {row.name || "—"}
                {isSelf ? (
                  <span
                    style={{
                      marginLeft: 8,
                      fontSize: 10.5,
                      fontWeight: 700,
                      color: brand.accentBlue,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                    }}
                  >
                    you
                  </span>
                ) : null}
              </div>
              <div
                style={{
                  color: brand.textMuted,
                  fontFamily: font,
                  fontSize: 12.5,
                  minWidth: 0,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={row.email}
              >
                {row.email}
              </div>
              <div
                style={{
                  color: brand.text,
                  fontFamily: font,
                  fontSize: 12.5,
                  fontWeight: 700,
                  textAlign: "right",
                }}
              >
                {Number(row.total_labels_processed || 0).toLocaleString()}
              </div>
              <div
                style={{
                  color: "#fda4af",
                  fontFamily: font,
                  fontSize: 12.5,
                  fontWeight: 700,
                  textAlign: "right",
                }}
              >
                {Number(row.risky_customer_count || 0).toLocaleString()}
              </div>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  fontFamily: font,
                  fontSize: 11.5,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                <span style={{ color: row.has_master_ocr_data ? "#86efac" : brand.textDim }}>
                  {row.has_master_ocr_data ? "Available" : "Missing"}
                </span>
                <span
                  style={{
                    color: row.has_meesho_master_ocr_data ? "#86efac" : brand.textDim,
                    fontWeight: 600,
                    fontSize: 10.5,
                  }}
                  title={
                    row.has_meesho_master_ocr_data
                      ? `${Number(row.meesho_master_records || 0).toLocaleString()} Meesho rows`
                      : "No Meesho master data yet"
                  }
                >
                  M: {row.has_meesho_master_ocr_data ? "Yes" : "No"}
                </span>
                <span
                  style={{
                    color: row.has_flipkart_master_ocr_data ? "#86efac" : brand.textDim,
                    fontWeight: 600,
                    fontSize: 10.5,
                  }}
                  title={
                    row.has_flipkart_master_ocr_data
                      ? `${Number(row.flipkart_master_records || 0).toLocaleString()} Flipkart rows`
                      : "No Flipkart master data yet"
                  }
                >
                  F: {row.has_flipkart_master_ocr_data ? "Yes" : "No"}
                </span>
              </div>
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  fontFamily: font,
                  fontSize: 11.5,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                }}
              >
                <span style={{ color: row.has_suspicious_customer_data ? "#86efac" : brand.textDim }}>
                  {row.has_suspicious_customer_data ? "Available" : "Missing"}
                </span>
                <span
                  style={{
                    color: row.has_meesho_suspicious_customer_data ? "#86efac" : brand.textDim,
                    fontWeight: 600,
                    fontSize: 10.5,
                  }}
                  title={
                    row.has_meesho_suspicious_customer_data
                      ? `${Number(row.meesho_suspicious_records || 0).toLocaleString()} Meesho suspicious rows`
                      : "No Meesho suspicious data yet"
                  }
                >
                  M: {row.has_meesho_suspicious_customer_data ? "Yes" : "No"}
                </span>
                <span
                  style={{
                    color: row.has_flipkart_suspicious_customer_data ? "#86efac" : brand.textDim,
                    fontWeight: 600,
                    fontSize: 10.5,
                  }}
                  title={
                    row.has_flipkart_suspicious_customer_data
                      ? `${Number(row.flipkart_suspicious_records || 0).toLocaleString()} Flipkart suspicious rows`
                      : "No Flipkart suspicious data yet"
                  }
                >
                  F: {row.has_flipkart_suspicious_customer_data ? "Yes" : "No"}
                </span>
              </div>
              <div
                style={{
                  color: brand.textDim,
                  fontFamily: font,
                  fontSize: 12,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  minWidth: 0,
                }}
                title={formatCreatedAt(row.created_at)}
              >
                {formatCreatedAt(row.created_at)}
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  alignItems: "center",
                  gap: 8,
                  flexWrap: "wrap",
                  minWidth: 0,
                }}
              >
                <span
                  style={{
                    fontFamily: font,
                    fontSize: 11,
                    fontWeight: 700,
                    color: row.is_admin ? brand.accentPurple : brand.textDim,
                    textTransform: "uppercase",
                    letterSpacing: "0.06em",
                  }}
                >
                  {row.is_admin ? "Admin" : "User"}
                </span>
                <button
                  type="button"
                  onClick={() => handleToggleRole(row)}
                  disabled={pending || pendingUserId !== null || pendingBulk}
                  style={{
                    borderRadius: 10,
                    border: `1px solid ${row.is_admin ? "rgba(248, 113, 113, 0.45)" : brand.border}`,
                    background: pending
                      ? brand.textDim
                      : row.is_admin
                        ? "rgba(127, 29, 29, 0.35)"
                        : brand.gradientCta,
                    color: "#fff",
                    fontFamily: font,
                    fontSize: 12,
                    fontWeight: 700,
                    padding: "7px 10px",
                    whiteSpace: "nowrap",
                    cursor: pending || pendingUserId !== null || pendingBulk ? "not-allowed" : "pointer",
                    opacity: pendingUserId !== null || pendingBulk ? 0.6 : 1,
                  }}
                >
                  {buttonLabel}
                </button>
                <button
                  type="button"
                  onClick={() => handleDownloadUserMasterData(row)}
                  disabled={downloadingMasterUserId === row.id || !row.has_master_ocr_data}
                  style={{
                    borderRadius: 10,
                    border: `1px solid ${brand.border}`,
                    background: "rgba(255,255,255,0.08)",
                    color: brand.text,
                    fontFamily: font,
                    fontSize: 12,
                    fontWeight: 700,
                    padding: "7px 10px",
                    whiteSpace: "nowrap",
                    cursor:
                      downloadingMasterUserId === row.id || !row.has_master_ocr_data
                        ? "not-allowed"
                        : "pointer",
                    opacity: downloadingMasterUserId === row.id || !row.has_master_ocr_data ? 0.7 : 1,
                  }}
                  title="Download this user's combined OCR master CSV (Meesho + Flipkart)"
                >
                  {downloadingMasterUserId === row.id
                    ? "Downloading..."
                    : row.has_master_ocr_data
                      ? "Master CSV"
                      : "No master"}
                </button>
                {ADMIN_OCR_PLATFORMS.map((platform) => {
                  const flagKey = `has_${platform}_master_ocr_data`;
                  const available = Boolean(row[flagKey]);
                  const platformKey = `${row.id}:${platform}`;
                  const downloading = downloadingMasterPlatformKey === platformKey;
                  const label = PLATFORM_LABELS[platform] || platform;
                  return (
                    <button
                      key={platform}
                      type="button"
                      onClick={() => handleDownloadUserMasterData(row, platform)}
                      disabled={downloading || !available}
                      style={{
                        borderRadius: 10,
                        border: `1px solid ${brand.border}`,
                        background: available ? "rgba(96, 165, 250, 0.18)" : "rgba(255,255,255,0.05)",
                        color: brand.text,
                        fontFamily: font,
                        fontSize: 12,
                        fontWeight: 700,
                        padding: "7px 10px",
                        whiteSpace: "nowrap",
                        cursor: downloading || !available ? "not-allowed" : "pointer",
                        opacity: downloading || !available ? 0.7 : 1,
                      }}
                      title={
                        available
                          ? `Download this user's ${label} master CSV`
                          : `${label} master CSV is not available for this user yet`
                      }
                    >
                      {downloading
                        ? "Downloading..."
                        : available
                          ? `${label} CSV`
                          : `No ${label}`}
                    </button>
                  );
                })}
                <button
                  type="button"
                  onClick={() => handleDownloadUserSuspiciousData(row)}
                  disabled={
                    downloadingSuspiciousUserId === row.id || !row.has_suspicious_customer_data
                  }
                  style={{
                    borderRadius: 10,
                    border: `1px solid ${brand.border}`,
                    background: "rgba(255,255,255,0.08)",
                    color: brand.text,
                    fontFamily: font,
                    fontSize: 12,
                    fontWeight: 700,
                    padding: "7px 10px",
                    whiteSpace: "nowrap",
                    cursor:
                      downloadingSuspiciousUserId === row.id || !row.has_suspicious_customer_data
                        ? "not-allowed"
                        : "pointer",
                    opacity:
                      downloadingSuspiciousUserId === row.id || !row.has_suspicious_customer_data
                        ? 0.7
                        : 1,
                  }}
                  title="Download this user's suspicious customers CSV"
                >
                  {downloadingSuspiciousUserId === row.id
                    ? "Downloading..."
                    : row.has_suspicious_customer_data
                      ? "Suspicious CSV"
                      : "No suspicious"}
                </button>
                {ADMIN_OCR_PLATFORMS.map((platform) => {
                  const flagKey = `has_${platform}_suspicious_customer_data`;
                  const available = Boolean(row[flagKey]);
                  const platformKey = `${row.id}:${platform}`;
                  const downloading = downloadingSuspiciousPlatformKey === platformKey;
                  const label = PLATFORM_LABELS[platform] || platform;
                  return (
                    <button
                      key={`suspicious-${platform}`}
                      type="button"
                      onClick={() => handleDownloadUserSuspiciousData(row, platform)}
                      disabled={downloading || !available}
                      style={{
                        borderRadius: 10,
                        border: `1px solid ${brand.border}`,
                        background: available ? "rgba(251, 113, 133, 0.18)" : "rgba(255,255,255,0.05)",
                        color: brand.text,
                        fontFamily: font,
                        fontSize: 12,
                        fontWeight: 700,
                        padding: "7px 10px",
                        whiteSpace: "nowrap",
                        cursor: downloading || !available ? "not-allowed" : "pointer",
                        opacity: downloading || !available ? 0.7 : 1,
                      }}
                      title={
                        available
                          ? `Download this user's ${label} suspicious customers CSV`
                          : `${label} suspicious customers CSV is not available for this user yet`
                      }
                    >
                      {downloading
                        ? "Downloading..."
                        : available
                          ? `${label} Suspicious`
                          : `No ${label}`}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div style={{ height: bottomPad }} />
      </div>
    </div>
  );
}

function WalletAuditSection({
  inputStyle,
  events,
  total,
  page,
  totalPages,
  setPage,
  loading,
  error,
  query,
  setQuery,
  onApplyQuery,
  onResetQuery,
  onRefresh,
}) {
  const summary =
    total <= 0
      ? "No wallet credits yet"
      : `Showing ${(page - 1) * WALLET_AUDIT_PAGE_SIZE + 1}-${Math.min(page * WALLET_AUDIT_PAGE_SIZE, total)} of ${total} credits`;
  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${brand.border}`,
        background: brand.bgCard,
        padding: 16,
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, color: brand.text, fontFamily: font, fontSize: 18, fontWeight: 800 }}>
            Wallet credit audit
          </h2>
          <p style={{ margin: "6px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
            Admin coin credits with actor, target, amount, note and timestamp.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
          }}
        >
          Refresh
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) auto auto", gap: 8 }}>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search actor, target, or note"
          style={inputStyle}
        />
        <button
          type="button"
          onClick={onApplyQuery}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
            fontWeight: 700,
          }}
        >
          Apply
        </button>
        <button
          type="button"
          onClick={onResetQuery}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.04)",
            padding: "8px 12px",
          }}
        >
          Reset
        </button>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>{summary}</div>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: page <= 1 ? "not-allowed" : "pointer" }}
          >
            Prev
          </button>
          <span style={{ color: brand.text, fontFamily: font, fontSize: 12.5, alignSelf: "center" }}>
            Page {page}/{totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: page >= totalPages ? "not-allowed" : "pointer" }}
          >
            Next
          </button>
        </div>
      </div>

      {loading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>Loading wallet credits...</div>
      ) : error ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{error}</div>
      ) : events.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>No wallet credit events found.</div>
      ) : (
        <WalletAuditEventsList events={events} />
      )}
    </div>
  );
}

function WalletAuditEventsList({ events }) {
  return (
    <div
      style={{
        display: "grid",
        gap: 8,
        maxHeight: AUDIT_LIST_HEIGHT,
        overflowY: "auto",
        paddingRight: 4,
      }}
    >
      {events.map((evt) => (
        <div
          key={evt.id}
          style={{
            borderRadius: 10,
            border: `1px solid ${brand.border}`,
            background: "rgba(255,255,255,0.03)",
            padding: "9px 10px",
          }}
        >
          <div style={{ color: brand.text, fontFamily: font, fontSize: 12.5, fontWeight: 700 }}>
            {evt.actor_name || evt.actor_email || "Unknown admin"} credited{" "}
            {evt.target_name || evt.target_email || `user #${evt.target_user_id}`}
          </div>
          <div style={{ color: "#86efac", fontFamily: font, fontSize: 12.5, marginTop: 3, fontWeight: 700 }}>
            +{Number(evt.delta || 0)} coins (balance: {Number(evt.balance_after || 0)})
          </div>
          {evt.note ? (
            <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12, marginTop: 3 }}>{evt.note}</div>
          ) : null}
          <div style={{ color: brand.textDim, fontFamily: font, fontSize: 11, marginTop: 3 }}>
            {formatCreatedAt(evt.created_at)}
          </div>
        </div>
      ))}
    </div>
  );
}

function AuditSection({
  inputStyle,
  events,
  total,
  page,
  totalPages,
  setPage,
  viewMode,
  setViewMode,
  loadingMore,
  hasMore,
  onLoadMore,
  loading,
  error,
  actorFilter,
  setActorFilter,
  targetFilter,
  setTargetFilter,
  fromDate,
  setFromDate,
  toDate,
  setToDate,
  onApplyFilters,
  onResetFilters,
  onExportCsv,
  csvColumns,
  setCsvColumns,
  onPresetDateRange,
  onRefresh,
}) {
  const isInfinite = viewMode === "infinite";
  const summary =
    total <= 0
      ? "No role changes yet"
      : isInfinite
        ? `Loaded ${events.length} of ${total} changes`
        : `Showing ${(page - 1) * AUDIT_PAGE_SIZE + 1}-${Math.min(page * AUDIT_PAGE_SIZE, total)} of ${total} changes`;
  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${brand.border}`,
        background: brand.bgCard,
        padding: 16,
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div>
          <h2 style={{ margin: 0, color: brand.text, fontFamily: font, fontSize: 18, fontWeight: 800 }}>
            Role audit trail
          </h2>
          <p style={{ margin: "6px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
            Server-side log of every admin role change.
          </p>
        </div>
        <div style={{ display: "inline-flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <div
            style={{
              display: "inline-flex",
              border: `1px solid ${brand.border}`,
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
            <button
              type="button"
              onClick={() => {
                if (viewMode === "paged") return;
                setViewMode("paged");
                setPage(1);
              }}
              style={{
                ...inputStyle,
                border: "none",
                borderRight: `1px solid ${brand.border}`,
                borderRadius: 0,
                padding: "8px 10px",
                cursor: "pointer",
                background: viewMode === "paged" ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.04)",
              }}
            >
              Paged
            </button>
            <button
              type="button"
              onClick={() => {
                if (viewMode === "infinite") return;
                setViewMode("infinite");
                setPage(1);
              }}
              style={{
                ...inputStyle,
                border: "none",
                borderRadius: 0,
                padding: "8px 10px",
                cursor: "pointer",
                background: viewMode === "infinite" ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.04)",
              }}
            >
              Infinite
            </button>
          </div>
          <button
            type="button"
            onClick={onExportCsv}
            disabled={!csvColumns.length}
            style={{
              ...inputStyle,
              cursor: !csvColumns.length ? "not-allowed" : "pointer",
              background: !csvColumns.length ? brand.textDim : brand.gradientCta,
              border: "none",
              color: "#fff",
              padding: "8px 12px",
              fontWeight: 700,
            }}
          >
            Export CSV
          </button>
          <button
            type="button"
            onClick={onRefresh}
            style={{
              ...inputStyle,
              cursor: "pointer",
              background: "rgba(255,255,255,0.06)",
              padding: "8px 12px",
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 8,
          alignItems: "center",
        }}
      >
        <input
          type="search"
          value={actorFilter}
          onChange={(e) => setActorFilter(e.target.value)}
          placeholder="Actor name/email"
          style={inputStyle}
        />
        <input
          type="search"
          value={targetFilter}
          onChange={(e) => setTargetFilter(e.target.value)}
          placeholder="Target name/email"
          style={inputStyle}
        />
        <input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} style={inputStyle} />
        <input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} style={inputStyle} />
        <div style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
          {[{ key: "today", label: "Today", days: 1 }, { key: "7d", label: "7d", days: 7 }, { key: "30d", label: "30d", days: 30 }].map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => onPresetDateRange(preset.days)}
              style={{
                ...inputStyle,
                cursor: "pointer",
                padding: "8px 10px",
                background: "rgba(255,255,255,0.06)",
              }}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onApplyFilters}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
            fontWeight: 700,
          }}
        >
          Apply filters
        </button>
        <button
          type="button"
          onClick={onResetFilters}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.04)",
            padding: "8px 12px",
          }}
        >
          Reset
        </button>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>CSV export columns</div>
          <div style={{ display: "inline-flex", gap: 8 }}>
            <button
              type="button"
              onClick={() => setCsvColumns(CSV_COLUMNS)}
              style={{
                ...inputStyle,
                cursor: "pointer",
                padding: "6px 10px",
                background: "rgba(255,255,255,0.06)",
                fontSize: 12,
              }}
            >
              Select all
            </button>
            <button
              type="button"
              onClick={() => setCsvColumns([])}
              style={{
                ...inputStyle,
                cursor: "pointer",
                padding: "6px 10px",
                background: "rgba(255,255,255,0.04)",
                fontSize: 12,
              }}
            >
              Select none
            </button>
          </div>
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {CSV_COLUMNS.map((column) => {
            const checked = csvColumns.includes(column);
            return (
              <label
                key={column}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  border: `1px solid ${brand.border}`,
                  borderRadius: 10,
                  padding: "6px 8px",
                  color: brand.textMuted,
                  fontFamily: font,
                  fontSize: 12,
                }}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() =>
                    setCsvColumns((prev) => {
                      if (checked) return prev.filter((c) => c !== column);
                      return [...prev, column];
                    })
                  }
                />
                {column}
              </label>
            );
          })}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>{summary}</div>
        {isInfinite ? (
          <div style={{ color: brand.textDim, fontFamily: font, fontSize: 12 }}>
            Scroll log to load more rows.
          </div>
        ) : (
          <div style={{ display: "inline-flex", gap: 8 }}>
            <button
              type="button"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              style={{ ...inputStyle, padding: "7px 10px", cursor: page <= 1 ? "not-allowed" : "pointer" }}
            >
              Prev
            </button>
            <span style={{ color: brand.text, fontFamily: font, fontSize: 12.5, alignSelf: "center" }}>
              Page {page}/{totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              style={{ ...inputStyle, padding: "7px 10px", cursor: page >= totalPages ? "not-allowed" : "pointer" }}
            >
              Next
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>Loading audit log...</div>
      ) : error ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{error}</div>
      ) : events.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>No role updates recorded yet.</div>
      ) : (
        <AuditEventsList events={events} onReachBottom={isInfinite ? onLoadMore : null} />
      )}
      {isInfinite && events.length > 0 ? (
        <div style={{ display: "flex", justifyContent: "center" }}>
          {loadingMore ? (
            <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
              Loading more audit rows...
            </div>
          ) : hasMore ? (
            <button
              type="button"
              onClick={onLoadMore}
              style={{
                ...inputStyle,
                cursor: "pointer",
                padding: "8px 12px",
                background: "rgba(255,255,255,0.06)",
              }}
            >
              Load more
            </button>
          ) : (
            <div style={{ color: brand.textDim, fontFamily: font, fontSize: 12 }}>All changes loaded.</div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function AuditEventsList({ events, onReachBottom }) {
  return (
    <div
      style={{
        display: "grid",
        gap: 8,
        maxHeight: AUDIT_LIST_HEIGHT,
        overflowY: "auto",
        paddingRight: 4,
      }}
      onScroll={(e) => {
        const el = e.currentTarget;
        if (onReachBottom && el.scrollTop + el.clientHeight >= el.scrollHeight - 80) {
          onReachBottom();
        }
      }}
    >
      {events.map((evt) => (
        <div
          key={evt.id}
          style={{
            borderRadius: 10,
            border: `1px solid ${brand.border}`,
            background: "rgba(255,255,255,0.03)",
            padding: "9px 10px",
          }}
        >
          <div style={{ color: brand.text, fontFamily: font, fontSize: 12.5, fontWeight: 700 }}>
            {evt.actor_name || evt.actor_email || "Unknown admin"} changed{" "}
            {evt.target_name || evt.target_email || `user #${evt.target_user_id}`}
          </div>
          <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12, marginTop: 3 }}>
            {evt.prev_is_admin ? "Admin" : "User"} {"->"} {evt.next_is_admin ? "Admin" : "User"}
          </div>
          <div style={{ color: brand.textDim, fontFamily: font, fontSize: 11, marginTop: 3 }}>
            {formatCreatedAt(evt.created_at)}
          </div>
        </div>
      ))}
    </div>
  );
}

function AdminOcrSection({
  inputStyle,
  tasks,
  tasksTotal,
  tasksPage,
  setTasksPage,
  tasksLoading,
  tasksError,
  ocrQuery,
  setOcrQuery,
  onApplyTaskSearch,
  onRefreshTasks,
  selectedTaskId,
  setSelectedTaskId,
  rows,
  rowsTotal,
  rowsPage,
  setRowsPage,
  rowsLoading,
  rowsError,
  rowsQuery,
  setRowsQuery,
  onApplyRowsSearch,
  onRefreshRows,
}) {
  const tasksTotalPages = Math.max(1, Math.ceil((tasksTotal || 0) / 20));
  const rowsTotalPages = Math.max(1, Math.ceil((rowsTotal || 0) / 30));
  const rowColumns = rows.length ? Object.keys(rows[0]) : [];
  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${brand.border}`,
        background: brand.bgCard,
        padding: 16,
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, color: brand.text, fontFamily: font, fontSize: 18, fontWeight: 800 }}>
            OCR server storage inspector
          </h2>
          <p style={{ margin: "6px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
            Admin-only viewer for OCR CSV rows stored on server.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefreshTasks}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
          }}
        >
          Refresh tasks
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) auto", gap: 10 }}>
        <input
          type="search"
          value={ocrQuery}
          onChange={(e) => setOcrQuery(e.target.value)}
          placeholder="Search task/user/email"
          style={inputStyle}
        />
        <button
          type="button"
          onClick={onApplyTaskSearch}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: brand.gradientCta,
            border: "none",
            color: "#fff",
            padding: "10px 14px",
            fontWeight: 700,
          }}
        >
          Search tasks
        </button>
      </div>

      {tasksLoading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>Loading OCR tasks...</div>
      ) : tasksError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{tasksError}</div>
      ) : tasks.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>No OCR tasks found.</div>
      ) : (
        <div
          style={{
            display: "grid",
            gap: 8,
            maxHeight: 220,
            overflowY: "auto",
            paddingRight: 4,
          }}
        >
          {tasks.map((t) => {
            const active = selectedTaskId === t.task_id;
            return (
              <button
                key={t.task_id}
                type="button"
                onClick={() => setSelectedTaskId(t.task_id)}
                style={{
                  textAlign: "left",
                  borderRadius: 10,
                  border: `1px solid ${active ? "rgba(59,130,246,0.6)" : brand.border}`,
                  background: active ? "rgba(59,130,246,0.16)" : "rgba(255,255,255,0.03)",
                  padding: "8px 10px",
                  color: brand.text,
                  fontFamily: font,
                  cursor: "pointer",
                }}
              >
                <div style={{ fontSize: 12.5, fontWeight: 700 }}>{t.task_id}</div>
                <div style={{ fontSize: 12, color: brand.textMuted, marginTop: 2 }}>
                  {t.user_email || `user #${t.user_id}`} · {t.status} · {formatCreatedAt(t.created_at)}
                </div>
              </button>
            );
          })}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
          OCR tasks: {tasksTotal}
        </div>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            disabled={tasksPage <= 1}
            onClick={() => setTasksPage((p) => Math.max(1, p - 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: tasksPage <= 1 ? "not-allowed" : "pointer" }}
          >
            Prev
          </button>
          <span style={{ color: brand.text, fontFamily: font, fontSize: 12.5, alignSelf: "center" }}>
            Page {tasksPage}/{tasksTotalPages}
          </span>
          <button
            type="button"
            disabled={tasksPage >= tasksTotalPages}
            onClick={() => setTasksPage((p) => Math.min(tasksTotalPages, p + 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: tasksPage >= tasksTotalPages ? "not-allowed" : "pointer" }}
          >
            Next
          </button>
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${brand.border}` }} />

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div style={{ color: brand.text, fontFamily: font, fontSize: 13, fontWeight: 700 }}>
          Task rows preview {selectedTaskId ? `(${selectedTaskId})` : ""}
        </div>
        <button
          type="button"
          onClick={onRefreshRows}
          disabled={!selectedTaskId}
          style={{
            ...inputStyle,
            cursor: selectedTaskId ? "pointer" : "not-allowed",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
          }}
        >
          Refresh rows
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) auto", gap: 10 }}>
        <input
          type="search"
          value={rowsQuery}
          onChange={(e) => setRowsQuery(e.target.value)}
          placeholder="Search row contents (Order ID, Name, etc.)"
          style={inputStyle}
        />
        <button
          type="button"
          onClick={onApplyRowsSearch}
          disabled={!selectedTaskId}
          style={{
            ...inputStyle,
            cursor: selectedTaskId ? "pointer" : "not-allowed",
            background: brand.gradientCta,
            border: "none",
            color: "#fff",
            padding: "10px 14px",
            fontWeight: 700,
          }}
        >
          Search rows
        </button>
      </div>

      {rowsLoading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>Loading OCR rows...</div>
      ) : rowsError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{rowsError}</div>
      ) : rowColumns.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
          Select a completed OCR task to preview stored CSV rows.
        </div>
      ) : (
        <div style={{ maxHeight: 320, overflow: "auto", border: `1px solid ${brand.border}`, borderRadius: 10 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: font, fontSize: 12.5 }}>
            <thead>
              <tr>
                {rowColumns.map((col) => (
                  <th
                    key={col}
                    style={{
                      position: "sticky",
                      top: 0,
                      background: "rgba(15,23,42,0.94)",
                      borderBottom: `1px solid ${brand.border}`,
                      textAlign: "left",
                      padding: "8px 10px",
                      color: brand.textMuted,
                    }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={`row-${idx}`} style={{ borderBottom: `1px solid ${brand.border}` }}>
                  {rowColumns.map((col) => (
                    <td key={`${idx}-${col}`} style={{ padding: "8px 10px", color: brand.text }}>
                      {String(r[col] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>Matching rows: {rowsTotal}</div>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            disabled={rowsPage <= 1}
            onClick={() => setRowsPage((p) => Math.max(1, p - 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: rowsPage <= 1 ? "not-allowed" : "pointer" }}
          >
            Prev
          </button>
          <span style={{ color: brand.text, fontFamily: font, fontSize: 12.5, alignSelf: "center" }}>
            Page {rowsPage}/{rowsTotalPages}
          </span>
          <button
            type="button"
            disabled={rowsPage >= rowsTotalPages}
            onClick={() => setRowsPage((p) => Math.min(rowsTotalPages, p + 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: rowsPage >= rowsTotalPages ? "not-allowed" : "pointer" }}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function AdminReturnSection({
  inputStyle,
  tasks,
  tasksTotal,
  tasksPage,
  setTasksPage,
  tasksLoading,
  tasksError,
  returnQuery,
  setReturnQuery,
  onApplyTaskSearch,
  onRefreshTasks,
  selectedTaskId,
  setSelectedTaskId,
  rows,
  rowsTotal,
  rowsPage,
  setRowsPage,
  rowsLoading,
  rowsError,
  rowsQuery,
  setRowsQuery,
  onApplyRowsSearch,
  onRefreshRows,
}) {
  const tasksTotalPages = Math.max(1, Math.ceil((tasksTotal || 0) / 20));
  const rowsTotalPages = Math.max(1, Math.ceil((rowsTotal || 0) / 30));
  const rowColumns = rows.length ? Object.keys(rows[0]) : [];
  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${brand.border}`,
        background: brand.bgCard,
        padding: 16,
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, color: brand.text, fontFamily: font, fontSize: 18, fontWeight: 800 }}>
            Return analysis storage inspector
          </h2>
          <p style={{ margin: "6px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
            Admin-only viewer for return-analysis CSV rows stored on server.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefreshTasks}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
          }}
        >
          Refresh tasks
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) auto", gap: 10 }}>
        <input
          type="search"
          value={returnQuery}
          onChange={(e) => setReturnQuery(e.target.value)}
          placeholder="Search task/user/email"
          style={inputStyle}
        />
        <button
          type="button"
          onClick={onApplyTaskSearch}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: brand.gradientCta,
            border: "none",
            color: "#fff",
            padding: "10px 14px",
            fontWeight: 700,
          }}
        >
          Search tasks
        </button>
      </div>

      {tasksLoading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
          Loading return analysis tasks...
        </div>
      ) : tasksError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{tasksError}</div>
      ) : tasks.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
          No return analysis tasks found.
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gap: 8,
            maxHeight: 220,
            overflowY: "auto",
            paddingRight: 4,
          }}
        >
          {tasks.map((t) => {
            const active = selectedTaskId === t.task_id;
            return (
              <button
                key={t.task_id}
                type="button"
                onClick={() => setSelectedTaskId(t.task_id)}
                style={{
                  textAlign: "left",
                  borderRadius: 10,
                  border: `1px solid ${active ? "rgba(59,130,246,0.6)" : brand.border}`,
                  background: active ? "rgba(59,130,246,0.16)" : "rgba(255,255,255,0.03)",
                  padding: "8px 10px",
                  color: brand.text,
                  fontFamily: font,
                  cursor: "pointer",
                }}
              >
                <div style={{ fontSize: 12.5, fontWeight: 700 }}>{t.task_id}</div>
                <div style={{ fontSize: 12, color: brand.textMuted, marginTop: 2 }}>
                  {t.user_email || `user #${t.user_id}`} · {t.status} · {formatCreatedAt(t.created_at)}
                </div>
              </button>
            );
          })}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
          Return analysis tasks: {tasksTotal}
        </div>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            disabled={tasksPage <= 1}
            onClick={() => setTasksPage((p) => Math.max(1, p - 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: tasksPage <= 1 ? "not-allowed" : "pointer" }}
          >
            Prev
          </button>
          <span style={{ color: brand.text, fontFamily: font, fontSize: 12.5, alignSelf: "center" }}>
            Page {tasksPage}/{tasksTotalPages}
          </span>
          <button
            type="button"
            disabled={tasksPage >= tasksTotalPages}
            onClick={() => setTasksPage((p) => Math.min(tasksTotalPages, p + 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: tasksPage >= tasksTotalPages ? "not-allowed" : "pointer" }}
          >
            Next
          </button>
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${brand.border}` }} />

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div style={{ color: brand.text, fontFamily: font, fontSize: 13, fontWeight: 700 }}>
          Task rows preview {selectedTaskId ? `(${selectedTaskId})` : ""}
        </div>
        <button
          type="button"
          onClick={onRefreshRows}
          disabled={!selectedTaskId}
          style={{
            ...inputStyle,
            cursor: selectedTaskId ? "pointer" : "not-allowed",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
          }}
        >
          Refresh rows
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 1fr) auto", gap: 10 }}>
        <input
          type="search"
          value={rowsQuery}
          onChange={(e) => setRowsQuery(e.target.value)}
          placeholder="Search row contents (Suborder Number, Name, etc.)"
          style={inputStyle}
        />
        <button
          type="button"
          onClick={onApplyRowsSearch}
          disabled={!selectedTaskId}
          style={{
            ...inputStyle,
            cursor: selectedTaskId ? "pointer" : "not-allowed",
            background: brand.gradientCta,
            border: "none",
            color: "#fff",
            padding: "10px 14px",
            fontWeight: 700,
          }}
        >
          Search rows
        </button>
      </div>

      {rowsLoading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
          Loading return analysis rows...
        </div>
      ) : rowsError ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{rowsError}</div>
      ) : rowColumns.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
          Select a completed return analysis task to preview stored CSV rows.
        </div>
      ) : (
        <div style={{ maxHeight: 320, overflow: "auto", border: `1px solid ${brand.border}`, borderRadius: 10 }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: font, fontSize: 12.5 }}>
            <thead>
              <tr>
                {rowColumns.map((col) => (
                  <th
                    key={col}
                    style={{
                      position: "sticky",
                      top: 0,
                      background: "rgba(15,23,42,0.94)",
                      borderBottom: `1px solid ${brand.border}`,
                      textAlign: "left",
                      padding: "8px 10px",
                      color: brand.textMuted,
                    }}
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={`row-${idx}`} style={{ borderBottom: `1px solid ${brand.border}` }}>
                  {rowColumns.map((col) => (
                    <td key={`${idx}-${col}`} style={{ padding: "8px 10px", color: brand.text }}>
                      {String(r[col] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
          Matching rows: {rowsTotal}
        </div>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            disabled={rowsPage <= 1}
            onClick={() => setRowsPage((p) => Math.max(1, p - 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: rowsPage <= 1 ? "not-allowed" : "pointer" }}
          >
            Prev
          </button>
          <span style={{ color: brand.text, fontFamily: font, fontSize: 12.5, alignSelf: "center" }}>
            Page {rowsPage}/{rowsTotalPages}
          </span>
          <button
            type="button"
            disabled={rowsPage >= rowsTotalPages}
            onClick={() => setRowsPage((p) => Math.min(rowsTotalPages, p + 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: rowsPage >= rowsTotalPages ? "not-allowed" : "pointer" }}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function AdminJobsSplitSection({
  inputStyle,
  jobs,
  total,
  page,
  setPage,
  loading,
  error,
  onRefresh,
}) {
  const totalPages = Math.max(1, Math.ceil((total || 0) / 20));
  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${brand.border}`,
        background: brand.bgCard,
        padding: 16,
        display: "grid",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div>
          <h2 style={{ margin: 0, color: brand.text, fontFamily: font, fontSize: 18, fontWeight: 800 }}>
            Crop split overview
          </h2>
          <p style={{ margin: "6px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>
            Latest crop jobs with normal/suspicious/pincode page split counts.
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          style={{
            ...inputStyle,
            cursor: "pointer",
            background: "rgba(255,255,255,0.06)",
            padding: "8px 12px",
          }}
        >
          Refresh jobs
        </button>
      </div>

      {loading ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>Loading jobs...</div>
      ) : error ? (
        <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{error}</div>
      ) : jobs.length === 0 ? (
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>No jobs found.</div>
      ) : (
        <div style={{ display: "grid", gap: 8 }}>
          {jobs.map((job) => {
            const s = splitCounts(job.options);
            return (
              <div
                key={job.id}
                style={{
                  borderRadius: 10,
                  border: `1px solid ${brand.border}`,
                  background: "rgba(255,255,255,0.03)",
                  padding: "9px 10px",
                }}
              >
                <div style={{ color: brand.text, fontFamily: font, fontSize: 12.5, fontWeight: 700 }}>
                  Job #{job.id} · {job.platform} · {job.user_email || `user #${job.user_id}`}
                </div>
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12, marginTop: 2 }}>
                  Status: {job.status} · Input pages: {job.total_input_pages || 0} · Output pages:{" "}
                  {job.total_output_pages || 0}
                </div>
                <div style={{ color: brand.textDim, fontFamily: font, fontSize: 11.5, marginTop: 2 }}>
                  Split {"->"} normal: {s.normal} · suspicious: {s.suspicious} · pincode: {s.pincode}
                  {s.manualCustomers || s.manualSuborders
                    ? ` · manual high risk: ${s.manualCustomers} customer(s), ${s.manualSuborders} suborder(s)`
                    : ""}
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
        <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12.5 }}>Total jobs: {total}</div>
        <div style={{ display: "inline-flex", gap: 8 }}>
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: page <= 1 ? "not-allowed" : "pointer" }}
          >
            Prev
          </button>
          <span style={{ color: brand.text, fontFamily: font, fontSize: 12.5, alignSelf: "center" }}>
            Page {page}/{totalPages}
          </span>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            style={{ ...inputStyle, padding: "7px 10px", cursor: page >= totalPages ? "not-allowed" : "pointer" }}
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
