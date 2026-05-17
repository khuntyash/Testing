import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { EMPTY_USER_DASHBOARD, fetchMyDashboard } from "../api/myDashboardApi.js";
import { PLATFORMS } from "../constants/platforms.js";
import { brand, font, homeHeroBackground } from "../theme/brandTheme.js";
import { PREMIUM_CROP_COIN_COST_PER_LABEL } from "../wallet/coinConfig.js";

const PLATFORM_LABELS = {
  meesho: "Meesho",
  flipkart: "Flipkart",
  ocr_labels: "OCR (CSV)",
  return_analysis: "Return analysis",
  unknown: "Unknown",
};

const PLATFORM_ACCENTS = {
  meesho: {
    color: "#ff4db8",
    soft: "rgba(255, 77, 184, 0.14)",
    border: "rgba(255, 77, 184, 0.32)",
  },
  flipkart: {
    color: "#60a5fa",
    soft: "rgba(96, 165, 250, 0.14)",
    border: "rgba(96, 165, 250, 0.32)",
  },
  ocr_labels: {
    color: "#a78bfa",
    soft: "rgba(167, 139, 250, 0.14)",
    border: "rgba(167, 139, 250, 0.32)",
  },
  return_analysis: {
    color: "#34d399",
    soft: "rgba(52, 211, 153, 0.14)",
    border: "rgba(52, 211, 153, 0.32)",
  },
  unknown: {
    color: "#94a3b8",
    soft: "rgba(148, 163, 184, 0.12)",
    border: "rgba(148, 163, 184, 0.28)",
  },
};

const STATUS_COLORS = {
  success: "#22c55e",
  failed: "#f87171",
  processing: "#fbbf24",
  pending: "#94a3b8",
};
const COIN_TO_INR = 0.5;

function platformDisplay(id) {
  if (!id) return "Unknown";
  if (PLATFORM_LABELS[id]) return PLATFORM_LABELS[id];
  const fromConst = PLATFORMS.find((p) => p.id === id);
  return fromConst?.name || id.charAt(0).toUpperCase() + id.slice(1);
}

function platformAccent(id) {
  return PLATFORM_ACCENTS[id] || PLATFORM_ACCENTS.unknown;
}

function statusColor(status) {
  return STATUS_COLORS[status] || STATUS_COLORS.pending;
}

function formatNumber(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "0";
  return num.toLocaleString();
}

function formatInr(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return "0.00";
  return num.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatStamp(value) {
  if (!value) return "";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return String(value);
  }
}

function formatRelative(value) {
  if (!value) return "";
  let stamp;
  try {
    stamp = new Date(value);
  } catch {
    return "";
  }
  const ms = Date.now() - stamp.getTime();
  if (!Number.isFinite(ms) || ms < 0) return formatStamp(value);
  const minutes = Math.floor(ms / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return formatStamp(value);
}

function StatCard({ label, value, hint, accent }) {
  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${brand.border}`,
        background: brand.bgCard,
        padding: "18px 18px 16px",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div
        aria-hidden
        style={{
          position: "absolute",
          inset: 0,
          background: accent
            ? `radial-gradient(120% 80% at 0% 0%, ${accent}, transparent 60%)`
            : "transparent",
          opacity: 0.55,
          pointerEvents: "none",
        }}
      />
      <div style={{ position: "relative" }}>
        <div
          style={{
            color: brand.textMuted,
            fontFamily: font,
            fontSize: 12,
            fontWeight: 700,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          {label}
        </div>
        <div
          style={{
            color: brand.text,
            fontFamily: font,
            fontSize: 28,
            fontWeight: 800,
            marginTop: 6,
            letterSpacing: "-0.5px",
          }}
        >
          {value}
        </div>
        {hint ? (
          <div
            style={{
              color: brand.textDim,
              fontFamily: font,
              fontSize: 12,
              marginTop: 6,
              lineHeight: 1.45,
            }}
          >
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function PlatformCard({ entry }) {
  const accent = platformAccent(entry.platform);
  const totalAmountSpendCoins =
    entry.platform === "meesho" || entry.platform === "flipkart"
      ? Math.max(0, Number(entry.premium_labels_billed || 0)) * PREMIUM_CROP_COIN_COST_PER_LABEL
      : 0;
  const totalAmountSpendInr = totalAmountSpendCoins * COIN_TO_INR;
  return (
    <div
      style={{
        borderRadius: 16,
        border: `1px solid ${accent.border}`,
        background: brand.bgCard,
        padding: 16,
        display: "grid",
        gap: 12,
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
      }}
    >
      <div
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "5px 10px",
            borderRadius: 999,
            background: accent.soft,
            border: `1px solid ${accent.border}`,
            color: accent.color,
            fontFamily: font,
            fontWeight: 700,
            fontSize: 13,
          }}
        >
          {platformDisplay(entry.platform)}
        </div>
        <div
          style={{
            color: brand.textMuted,
            fontFamily: font,
            fontSize: 11.5,
          }}
        >
          {entry.last_run_at ? `Last run ${formatRelative(entry.last_run_at)}` : "No runs yet"}
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
          gap: 10,
        }}
      >
        <MiniStat label="Total amount spend" value={`₹${formatInr(totalAmountSpendInr)}`} />
        <MiniStat label="Billable premium labels" value={formatNumber(entry.premium_labels_billed)} />
        <MiniStat label="Suspicious buyers" value={formatNumber(entry.suspicious_buyers_total)} />
        <MiniStat label="Suspicious labels found" value={formatNumber(entry.suspicious_pages_total)} />
      </div>
    </div>
  );
}

function MiniStat({ label, value }) {
  return (
    <div
      style={{
        borderRadius: 12,
        border: `1px solid ${brand.border}`,
        background: "rgba(255,255,255,0.02)",
        padding: "10px 12px",
      }}
    >
      <div style={{ color: brand.textDim, fontFamily: font, fontSize: 11, fontWeight: 600 }}>
        {label}
      </div>
      <div
        style={{
          color: brand.text,
          fontFamily: font,
          fontSize: 18,
          fontWeight: 800,
          marginTop: 4,
          letterSpacing: "-0.3px",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function RecentJobRow({ job }) {
  const accent = platformAccent(job.platform);
  return (
    <li
      style={{
        listStyle: "none",
        display: "grid",
        gridTemplateColumns: "minmax(0, 1fr) auto",
        gap: 10,
        padding: "12px 14px",
        borderRadius: 12,
        border: `1px solid ${brand.border}`,
        background: "rgba(255,255,255,0.02)",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              color: brand.text,
              fontFamily: font,
              fontWeight: 700,
              fontSize: 13,
            }}
          >
            Job #{job.id}
          </span>
          <span
            style={{
              padding: "2px 8px",
              borderRadius: 999,
              border: `1px solid ${accent.border}`,
              background: accent.soft,
              color: accent.color,
              fontFamily: font,
              fontWeight: 700,
              fontSize: 11,
            }}
          >
            {platformDisplay(job.platform)}
          </span>
          <span
            style={{
              color: statusColor(job.status),
              fontFamily: font,
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
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
          {formatNumber(job.total_output_labels)} labels · {formatNumber(job.total_input_pages)}{" "}
          pages · {formatNumber(job.total_input_files)} file
          {job.total_input_files === 1 ? "" : "s"}
        </div>
        {job.error_message ? (
          <div
            style={{
              marginTop: 4,
              color: "#fca5a5",
              fontFamily: font,
              fontSize: 11.5,
              maxWidth: 520,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={job.error_message}
          >
            {job.error_message}
          </div>
        ) : null}
      </div>
      <div
        style={{
          textAlign: "right",
          color: brand.textDim,
          fontFamily: font,
          fontSize: 11.5,
          whiteSpace: "nowrap",
          alignSelf: "center",
        }}
      >
        {job.created_at ? formatRelative(job.created_at) : "—"}
      </div>
    </li>
  );
}

export default function MyDashboardPage() {
  const { user } = useAuth();
  const [data, setData] = useState(EMPTY_USER_DASHBOARD);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let alive = true;
    const run = async () => {
      setLoading(true);
      setError("");
      try {
        const next = await fetchMyDashboard({ recentLimit: 5 });
        if (!alive) return;
        setData(next);
      } catch (err) {
        if (!alive) return;
        setData(EMPTY_USER_DASHBOARD);
        setError(err instanceof Error ? err.message : "Could not load your dashboard.");
      } finally {
        if (alive) setLoading(false);
      }
    };
    run();
    return () => {
      alive = false;
    };
  }, [reloadKey]);

  const summary = data.summary;
  const visiblePlatforms = useMemo(
    () => (Array.isArray(data.platforms) ? data.platforms.filter((entry) => entry?.platform !== "ocr_labels") : []),
    [data.platforms],
  );
  const recentActivityJobs = useMemo(
    () =>
      Array.isArray(data.recent_jobs)
        ? data.recent_jobs.filter((job) => (job?.platform || "").toLowerCase() !== "ocr_labels")
        : [],
    [data.recent_jobs],
  );

  const hasAnyJobs = summary.total_jobs > 0;
  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: homeHeroBackground,
        padding: "0 0 48px",
        fontFamily: font,
        color: brand.text,
      }}
    >
      <div
        style={{
          background: "linear-gradient(180deg, rgba(7, 10, 18, 0.96) 0%, rgba(6, 9, 16, 0.9) 100%)",
          borderBottom: "1px solid rgba(148, 163, 184, 0.14)",
          padding: "10px 16px",
          display: "grid",
          gridTemplateColumns: "auto minmax(0, 1fr) auto",
          alignItems: "center",
          gap: "8px 14px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", minWidth: 0 }}>
          <Link
            to="/"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 13,
              fontWeight: 600,
              color: "#cbd5e1",
              fontFamily: font,
              textDecoration: "none",
              padding: "8px 14px",
              borderRadius: 10,
              border: "2px solid rgba(148, 163, 184, 0.28)",
              background: "rgba(15, 23, 42, 0.45)",
              boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
              whiteSpace: "nowrap",
            }}
          >
            <span aria-hidden>←</span> All platforms
          </Link>
        </div>

        <nav
          aria-label="Switch platform cropper"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            minWidth: 0,
            overflowX: "auto",
            overflowY: "hidden",
            padding: "2px 2px",
            WebkitOverflowScrolling: "touch",
            scrollbarWidth: "thin",
          }}
        >
          {PLATFORMS.map((plat) => {
            return (
              <Link
                key={plat.id}
                to={`/${plat.id}`}
                title={`${plat.name} cropper`}
                style={{
                  flexShrink: 0,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "6px 14px 6px 9px",
                  borderRadius: 999,
                  textDecoration: "none",
                  fontFamily: font,
                  fontSize: 15,
                  fontWeight: 700,
                  color: "#f8fafc",
                  border: "2px solid rgba(148, 163, 184, 0.28)",
                  background: "rgba(15, 23, 42, 0.62)",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
                  whiteSpace: "nowrap",
                }}
              >
                <span
                  style={{
                    width: 20,
                    height: 20,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                    overflow: "hidden",
                    borderRadius: 5,
                    background: "rgba(15, 23, 42, 0.55)",
                  }}
                >
                  <img
                    src={plat.homeThumbnail || plat.logo}
                    alt={`${plat.name} logo`}
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      display: "block",
                    }}
                  />
                </span>
                <span>{plat.name}</span>
              </Link>
            );
          })}
          <Link
            to="/my-dashboard"
            title="My dashboard"
            style={{
              flexShrink: 0,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 14px",
              borderRadius: 999,
              textDecoration: "none",
              fontFamily: font,
              fontSize: 15,
              fontWeight: 700,
              color: "#f8fafc",
              border: "2px solid rgba(99, 102, 241, 0.74)",
              background: "linear-gradient(135deg, rgba(99, 102, 241, 0.24), rgba(168, 85, 247, 0.2))",
              boxShadow: "0 0 14px rgba(99, 102, 241, 0.28), inset 0 1px 0 rgba(255,255,255,0.08)",
              whiteSpace: "nowrap",
            }}
          >
            My dashboard
          </Link>
        </nav>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              fontSize: 13,
              fontWeight: 700,
              color: "#6ee7b7",
              fontFamily: font,
              padding: "8px 15px",
              borderRadius: 999,
              background: "linear-gradient(180deg, rgba(3, 56, 46, 0.84), rgba(4, 45, 40, 0.84))",
              border: "2px solid rgba(52, 211, 153, 0.5)",
              boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), 0 0 12px rgba(16, 185, 129, 0.15)",
              whiteSpace: "nowrap",
            }}
          >
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "#10b981",
                boxShadow: "0 0 10px #10b981",
              }}
            />
            Ready to upload
          </span>
        </div>
      </div>
      <div style={{ maxWidth: 1180, margin: "20px auto 0", display: "grid", gap: 20, padding: "0 20px" }}>
        {error ? (
          <div
            role="alert"
            style={{
              padding: "14px 16px",
              borderRadius: 12,
              border: "1px solid rgba(252, 165, 165, 0.4)",
              background: "rgba(185, 28, 28, 0.18)",
              color: "#fecaca",
              fontFamily: font,
              fontSize: 13,
              display: "flex",
              justifyContent: "space-between",
              gap: 12,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setReloadKey((k) => k + 1)}
              style={{
                padding: "6px 12px",
                borderRadius: 8,
                border: "1px solid rgba(252, 165, 165, 0.5)",
                background: "rgba(248, 113, 113, 0.15)",
                color: "#fecaca",
                fontFamily: font,
                fontWeight: 700,
                fontSize: 12,
                cursor: "pointer",
              }}
            >
              Retry
            </button>
          </div>
        ) : null}

        <section
          style={{
            display: "grid",
            gap: 14,
          }}
        >
          <div
            style={{
              borderRadius: 18,
              border: `1px solid ${brand.border}`,
              background: brand.bgCard,
              padding: 18,
              display: "grid",
              gap: 12,
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
              <h2
                style={{
                  margin: 0,
                  fontSize: 16,
                  fontWeight: 800,
                  color: brand.text,
                  letterSpacing: "-0.3px",
                }}
              >
                Platform breakdown
              </h2>
              <span style={{ color: brand.textDim, fontSize: 12 }}>
                Counts derived from your visible job history
              </span>
            </div>

            {loading && !hasAnyJobs ? (
              <p style={{ color: brand.textMuted, fontSize: 13, margin: 0 }}>
                Loading platform stats…
              </p>
            ) : visiblePlatforms.length === 0 ? (
              <div
                style={{
                  padding: "20px 14px",
                  borderRadius: 12,
                  border: `1px dashed ${brand.border}`,
                  background: "rgba(255,255,255,0.02)",
                  color: brand.textMuted,
                  fontSize: 13,
                  textAlign: "center",
                }}
              >
                No crop runs yet. Start a Meesho or Flipkart job and stats will appear here.
                <div style={{ marginTop: 10 }}>
                  <Link
                    to="/"
                    style={{
                      color: brand.accentPurple,
                      fontWeight: 700,
                      textDecoration: "none",
                    }}
                  >
                    Go to platforms →
                  </Link>
                </div>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 12 }}>
                {visiblePlatforms.map((entry) => (
                  <PlatformCard key={entry.platform} entry={entry} />
                ))}
              </div>
            )}
          </div>

        </section>

        <section
          style={{
            borderRadius: 18,
            border: `1px solid ${brand.border}`,
            background: brand.bgCard,
            padding: 18,
            display: "grid",
            gap: 12,
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
            <h2
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 800,
                letterSpacing: "-0.3px",
              }}
            >
              Recent activity
            </h2>
            <Link
              to="/history"
              style={{
                color: brand.accentBlue,
                fontFamily: font,
                fontWeight: 700,
                fontSize: 12,
                textDecoration: "none",
              }}
            >
              See all →
            </Link>
          </div>

          {loading && recentActivityJobs.length === 0 ? (
            <p style={{ color: brand.textMuted, fontSize: 13, margin: 0 }}>Loading recent jobs…</p>
          ) : recentActivityJobs.length === 0 ? (
            <div
              style={{
                padding: "20px 14px",
                borderRadius: 12,
                border: `1px dashed ${brand.border}`,
                background: "rgba(255,255,255,0.02)",
                color: brand.textMuted,
                fontSize: 13,
                textAlign: "center",
              }}
            >
              You haven&apos;t started any jobs yet. Once you upload labels, your recent runs will
              show up here.
            </div>
          ) : (
            <ul
              style={{
                display: "grid",
                gap: 10,
                margin: 0,
                padding: 0,
              }}
            >
              {recentActivityJobs.map((job) => (
                <RecentJobRow key={job.id} job={job} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
