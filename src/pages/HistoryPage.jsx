import { useEffect, useMemo, useState } from "react";
import { fetchCropHistoryJobDetail, fetchCropHistoryJobs } from "../api/historyApi.js";
import { PLATFORMS } from "../constants/platforms.js";
import { brand, font } from "../theme/brandTheme.js";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "success", label: "Success" },
  { value: "failed", label: "Failed" },
  { value: "processing", label: "Processing" },
  { value: "pending", label: "Pending" },
];
const EXTRA_PLATFORM_OPTIONS = [{ id: "ocr_labels", name: "OCR CSV (stored)" }];
const JOB_PAGE_SIZE = 100;
const JOB_ROW_HEIGHT = 108;
const JOB_LIST_HEIGHT = 520;
const JOB_CHUNK_SIZE = 25;

function platformName(platformId) {
  const row = [...PLATFORMS, ...EXTRA_PLATFORM_OPTIONS].find((p) => p.id === platformId);
  return row?.name || platformId || "Unknown";
}

function toUtcStartIso(dateText) {
  if (!dateText) return "";
  return `${dateText}T00:00:00.000Z`;
}

function toUtcEndIso(dateText) {
  if (!dateText) return "";
  return `${dateText}T23:59:59.999Z`;
}

function statusPillColor(status) {
  if (status === "success") return "#22c55e";
  if (status === "failed") return "#f87171";
  if (status === "processing") return "#fbbf24";
  return "#94a3b8";
}

function splitCounts(options) {
  const o = options && typeof options === "object" ? options : {};
  const normal = Number(o.normal_pages || 0);
  const suspicious = Number(o.risky_pages || 0);
  const pincode = Number(o.selected_pincode_pages || 0);
  const manualCustomers = Number(o.manual_high_risk_customers_total || 0);
  const manualSuborders = Number(o.manual_high_risk_suborders_total || 0);
  return { normal, suspicious, pincode, manualCustomers, manualSuborders };
}

function normalizeCourierName(name) {
  const label = String(name || "Unknown").trim() || "Unknown";
  return /^xpress\s*bees?$/i.test(label) ? "Xpress Bees" : label;
}

function courierCounts(options) {
  const raw = options && typeof options === "object" ? options.courier_counts : null;
  if (!raw || typeof raw !== "object") return [];
  const entries = Object.entries(raw)
    .map(([name, value]) => [normalizeCourierName(name), Number(value) || 0])
    .filter(([, value]) => value > 0);
  entries.sort((a, b) => {
    if (a[0] === "Unknown" && b[0] !== "Unknown") return 1;
    if (b[0] === "Unknown" && a[0] !== "Unknown") return -1;
    if (b[1] !== a[1]) return b[1] - a[1];
    return a[0].localeCompare(b[0]);
  });
  return entries;
}

export default function HistoryPage() {
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [selectedId, setSelectedId] = useState(null);
  const [selectedJob, setSelectedJob] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const [platformFilter, setPlatformFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sortFilter, setSortFilter] = useState("newest");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [jobScrollTop, setJobScrollTop] = useState(0);
  const [renderLimit, setRenderLimit] = useState(JOB_CHUNK_SIZE);

  const [appliedFilters, setAppliedFilters] = useState({
    platform: "",
    status: "",
    sort: "newest",
    from: "",
    to: "",
  });

  const [page, setPage] = useState(1);
  const offset = (page - 1) * JOB_PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(total / JOB_PAGE_SIZE));

  useEffect(() => {
    let alive = true;
    const run = async () => {
      setLoading(true);
      setError("");
      try {
        const data = await fetchCropHistoryJobs({
          platformId: appliedFilters.platform,
          status: appliedFilters.status,
          sort: appliedFilters.sort,
          fromDate: toUtcStartIso(appliedFilters.from),
          toDate: toUtcEndIso(appliedFilters.to),
          limit: JOB_PAGE_SIZE,
          offset,
        });
        if (!alive) return;
        setJobs(data.jobs);
        setTotal(data.total);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof Error ? err.message : "Failed to load history.");
        setJobs([]);
        setTotal(0);
      } finally {
        if (alive) setLoading(false);
      }
    };
    run();
    return () => {
      alive = false;
    };
  }, [appliedFilters, offset]);

  useEffect(() => {
    setRenderLimit(JOB_CHUNK_SIZE);
    let cancelled = false;
    const tick = () => {
      if (cancelled) return;
      setRenderLimit((current) => {
        if (current >= jobs.length) return current;
        const next = Math.min(jobs.length, current + JOB_CHUNK_SIZE);
        if (next < jobs.length) {
          setTimeout(tick, 0);
        }
        return next;
      });
    };
    if (jobs.length > JOB_CHUNK_SIZE) {
      setTimeout(tick, 0);
    }
    return () => {
      cancelled = true;
    };
  }, [jobs]);

  useEffect(() => {
    if (!selectedId) {
      setSelectedJob(null);
      return;
    }
    let alive = true;
    const run = async () => {
      setDetailLoading(true);
      setDetailError("");
      try {
        const row = await fetchCropHistoryJobDetail(selectedId);
        if (!alive) return;
        setSelectedJob(row);
      } catch (err) {
        if (!alive) return;
        setSelectedJob(null);
        setDetailError(err instanceof Error ? err.message : "Could not load job details.");
      } finally {
        if (alive) setDetailLoading(false);
      }
    };
    run();
    return () => {
      alive = false;
    };
  }, [selectedId]);

  const summaryText = useMemo(() => {
    if (!total) return "No jobs found";
    const start = offset + 1;
    const end = Math.min(offset + jobs.length, total);
    return `Showing ${start}-${end} of ${total} jobs`;
  }, [jobs.length, offset, total]);

  const chunkedJobs = useMemo(() => jobs.slice(0, renderLimit), [jobs, renderLimit]);
  const startIndex = Math.max(0, Math.floor(jobScrollTop / JOB_ROW_HEIGHT) - 4);
  const visibleCount = Math.ceil(JOB_LIST_HEIGHT / JOB_ROW_HEIGHT) + 8;
  const endIndex = Math.min(chunkedJobs.length, startIndex + visibleCount);
  const visibleJobs = chunkedJobs.slice(startIndex, endIndex);
  const topPad = startIndex * JOB_ROW_HEIGHT;
  const bottomPad = Math.max(0, (chunkedJobs.length - endIndex) * JOB_ROW_HEIGHT);

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
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: brand.bgPage,
        padding: "24px 20px 30px",
      }}
    >
      <div style={{ maxWidth: 1180, margin: "0 auto", display: "grid", gap: 16 }}>
        <div
          style={{
            borderRadius: 16,
            border: `1px solid ${brand.border}`,
            background: brand.bgCard,
            padding: 16,
          }}
        >
          <h1
            style={{
              margin: 0,
              color: brand.text,
              fontFamily: font,
              fontWeight: 800,
              fontSize: 26,
            }}
          >
            Crop History
          </h1>
          <p style={{ margin: "8px 0 0", color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
            Filter crop jobs by status/date/platform, then inspect detailed metrics for each run.
          </p>
        </div>

        <div
          style={{
            borderRadius: 16,
            border: `1px solid ${brand.border}`,
            background: brand.bgCard,
            padding: 14,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 10,
          }}
        >
          <select
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
            style={inputStyle}
          >
            <option value="">All platforms</option>
            {[...PLATFORMS, ...EXTRA_PLATFORM_OPTIONS].map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            style={inputStyle}
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s.value || "all"} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>

          <select
            value={sortFilter}
            onChange={(e) => setSortFilter(e.target.value)}
            style={inputStyle}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
          </select>

          <input
            type="date"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            style={inputStyle}
          />
          <input
            type="date"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            style={inputStyle}
          />

          <button
            type="button"
            onClick={() => {
              setAppliedFilters({
                platform: platformFilter,
                status: statusFilter,
                sort: sortFilter,
                from: fromDate,
                to: toDate,
              });
              setPage(1);
            }}
            style={{
              ...inputStyle,
              cursor: "pointer",
              background: brand.gradientCta,
              color: "#fff",
              border: "none",
              fontWeight: 700,
            }}
          >
            Apply filters
          </button>

          <button
            type="button"
            onClick={() => {
              setPlatformFilter("");
              setStatusFilter("");
              setSortFilter("newest");
              setFromDate("");
              setToDate("");
              setAppliedFilters({ platform: "", status: "", sort: "newest", from: "", to: "" });
              setPage(1);
            }}
            style={{
              ...inputStyle,
              cursor: "pointer",
              background: "rgba(255,255,255,0.04)",
            }}
          >
            Reset
          </button>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 360px", gap: 12 }}>
          <div
            style={{
              borderRadius: 16,
              border: `1px solid ${brand.border}`,
              background: brand.bgCard,
              padding: 14,
              minHeight: 480,
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 10,
              }}
            >
              <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
                {summaryText}
              </div>
              <div style={{ display: "inline-flex", gap: 8 }}>
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  style={{
                    ...inputStyle,
                    padding: "7px 10px",
                    cursor: page <= 1 ? "not-allowed" : "pointer",
                    opacity: page <= 1 ? 0.6 : 1,
                  }}
                >
                  Prev
                </button>
                <span
                  style={{ color: brand.text, fontFamily: font, fontSize: 13, alignSelf: "center" }}
                >
                  Page {page}/{totalPages}
                </span>
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  style={{
                    ...inputStyle,
                    padding: "7px 10px",
                    cursor: page >= totalPages ? "not-allowed" : "pointer",
                    opacity: page >= totalPages ? 0.6 : 1,
                  }}
                >
                  Next
                </button>
              </div>
            </div>

            {loading ? (
              <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
                Loading history...
              </div>
            ) : error ? (
              <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{error}</div>
            ) : jobs.length === 0 ? (
              <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
                No history jobs found for current filters.
              </div>
            ) : (
              <div style={{ display: "grid", gap: 8 }}>
                <div style={{ color: brand.textDim, fontFamily: font, fontSize: 11.5 }}>
                  Rendered {chunkedJobs.length}/{jobs.length} rows on this page
                </div>
                <div
                  style={{ maxHeight: JOB_LIST_HEIGHT, overflowY: "auto" }}
                  onScroll={(e) => setJobScrollTop(e.currentTarget.scrollTop)}
                >
                  <div style={{ height: topPad }} />
                  <div style={{ display: "grid", gap: 8 }}>
                    {visibleJobs.map((job) => (
                      <button
                        key={job.id}
                        type="button"
                        onClick={() => setSelectedId(job.id)}
                        style={{
                          textAlign: "left",
                          cursor: "pointer",
                          borderRadius: 12,
                          border: `1px solid ${selectedId === job.id ? brand.accentPurple : brand.border}`,
                          background:
                            selectedId === job.id
                              ? "rgba(167,139,250,0.08)"
                              : "rgba(255,255,255,0.02)",
                          padding: "10px 12px",
                          minHeight: JOB_ROW_HEIGHT,
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            gap: 8,
                            flexWrap: "wrap",
                          }}
                        >
                          <div
                            style={{
                              color: brand.text,
                              fontFamily: font,
                              fontSize: 13,
                              fontWeight: 700,
                            }}
                          >
                            Job #{job.id} · {platformName(job.platform)}
                          </div>
                          <span
                            style={{
                              color: statusPillColor(job.status),
                              fontFamily: font,
                              fontSize: 11,
                              fontWeight: 700,
                              textTransform: "uppercase",
                            }}
                          >
                            {job.status || "unknown"}
                          </span>
                        </div>
                        <div
                          style={{
                            marginTop: 4,
                            color: brand.textMuted,
                            fontFamily: font,
                            fontSize: 12,
                          }}
                        >
                          Labels: {job.total_output_labels || 0} · Pages:{" "}
                          {job.total_input_pages || 0} · Files: {job.total_input_files || 0} ·
                          Duration: {job.duration_ms || 0}ms
                        </div>
                        {(() => {
                          const s = splitCounts(job.options);
                          if (
                            !s.suspicious &&
                            !s.pincode &&
                            !s.manualCustomers &&
                            !s.manualSuborders
                          )
                            return null;
                          return (
                            <div
                              style={{
                                marginTop: 4,
                                color: brand.textDim,
                                fontFamily: font,
                                fontSize: 11.5,
                              }}
                            >
                              Split {"->"} normal: {s.normal} · suspicious: {s.suspicious} ·
                              pincode: {s.pincode}
                              {s.manualCustomers || s.manualSuborders
                                ? ` · manual high risk: ${s.manualCustomers} customer(s), ${s.manualSuborders} suborder(s)`
                                : ""}
                            </div>
                          );
                        })()}
                        <div
                          style={{
                            marginTop: 4,
                            color: brand.textDim,
                            fontFamily: font,
                            fontSize: 11,
                          }}
                        >
                          {job.created_at
                            ? new Date(job.created_at).toLocaleString()
                            : "No timestamp"}
                        </div>
                      </button>
                    ))}
                  </div>
                  <div style={{ height: bottomPad }} />
                </div>
              </div>
            )}
          </div>

          <div
            style={{
              borderRadius: 16,
              border: `1px solid ${brand.border}`,
              background: brand.bgCard,
              padding: 14,
              minHeight: 480,
            }}
          >
            <h2
              style={{
                margin: 0,
                color: brand.text,
                fontFamily: font,
                fontWeight: 700,
                fontSize: 18,
              }}
            >
              Job details
            </h2>
            {!selectedId ? (
              <p style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
                Select a job to view details.
              </p>
            ) : detailLoading ? (
              <p style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
                Loading job details...
              </p>
            ) : detailError ? (
              <p style={{ color: "#fca5a5", fontFamily: font, fontSize: 13 }}>{detailError}</p>
            ) : selectedJob ? (
              <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
                <div style={{ color: brand.text, fontFamily: font, fontSize: 13, fontWeight: 700 }}>
                  Job #{selectedJob.id}
                </div>
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                  Platform: {platformName(selectedJob.platform)}
                </div>
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                  Status: {selectedJob.status}
                </div>
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                  Sort/Layout: {selectedJob.sort_by || "-"} / {selectedJob.layout || "-"}
                </div>
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                  Input files/pages: {selectedJob.total_input_files || 0} /{" "}
                  {selectedJob.total_input_pages || 0}
                </div>
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                  Output labels/pages: {selectedJob.total_output_labels || 0} /{" "}
                  {selectedJob.total_output_pages || 0}
                </div>
                {(() => {
                  const s = splitCounts(selectedJob.options);
                  if (!s.suspicious && !s.pincode && !s.manualCustomers && !s.manualSuborders)
                    return null;
                  return (
                    <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                      Split output pages: normal {s.normal} · suspicious {s.suspicious} · pincode{" "}
                      {s.pincode}
                      {s.manualCustomers || s.manualSuborders
                        ? ` · manual high risk ${s.manualCustomers} customer(s), ${s.manualSuborders} suborder(s)`
                        : ""}
                    </div>
                  );
                })()}
                {(() => {
                  const cc = courierCounts(selectedJob.options);
                  if (!cc.length) return null;
                  const summary = cc.map(([name, value]) => `${name}: ${value}`).join(" · ");
                  return (
                    <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                      Courier counts {"->"} {summary}
                    </div>
                  );
                })()}
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                  Duration: {selectedJob.duration_ms || 0}ms
                </div>
                <div style={{ color: brand.textMuted, fontFamily: font, fontSize: 12 }}>
                  Created:{" "}
                  {selectedJob.created_at ? new Date(selectedJob.created_at).toLocaleString() : "-"}
                </div>
                {selectedJob.error_message ? (
                  <div style={{ color: "#fca5a5", fontFamily: font, fontSize: 12 }}>
                    Error: {selectedJob.error_message}
                  </div>
                ) : null}
                <div
                  style={{
                    marginTop: 4,
                    borderTop: `1px solid ${brand.border}`,
                    paddingTop: 8,
                    color: brand.text,
                    fontFamily: font,
                    fontSize: 12,
                    fontWeight: 700,
                  }}
                >
                  Input files
                </div>
                {(selectedJob.files || []).length ? (
                  <div style={{ display: "grid", gap: 6 }}>
                    {selectedJob.files.map((f, idx) => (
                      <div
                        key={`${f.file_name}-${idx}`}
                        style={{
                          border: `1px solid ${brand.border}`,
                          borderRadius: 10,
                          padding: "7px 8px",
                          color: brand.textMuted,
                          fontFamily: font,
                          fontSize: 11.5,
                        }}
                      >
                        {f.file_name} · {f.input_pages || 0} page(s)
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ color: brand.textDim, fontFamily: font, fontSize: 12 }}>
                    No input file details for this run.
                  </div>
                )}
              </div>
            ) : (
              <p style={{ color: brand.textMuted, fontFamily: font, fontSize: 13 }}>
                Job details are unavailable.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
