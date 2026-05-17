import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { fetchUserHistoryBySuborder } from "../api/userHistoryApi.js";
import { brand, font } from "../theme/brandTheme.js";

const PANEL_BG = "rgba(14, 16, 22, 0.92)";
const PANEL_BORDER_STRONG = "rgba(148, 163, 184, 0.32)";
const HISTORY_GREEN_BG = "rgba(22, 101, 52, 0.24)";
const HISTORY_GREEN_BORDER = "rgba(74, 222, 128, 0.36)";
const HISTORY_GREEN_HEAD = "rgba(22, 101, 52, 0.42)";
const HISTORY_GREEN_DIVIDER = "1px solid rgba(74, 222, 128, 0.2)";

const ACTIVITY_SORT_OPTIONS = [
  { value: "row_type", label: "Type" },
  { value: "suborder_id", label: "Suborder" },
  { value: "order_date", label: "Print date" },
  { value: "sku", label: "SKU" },
  { value: "payment_mode", label: "Payment mode" },
  { value: "courier_partner", label: "Courier" },
  { value: "type_of_return", label: "Return type" },
  { value: "return_reason", label: "Reason" },
];

function normalizeSuborderParam(value) {
  return String(value || "").trim();
}

function sortRows(rows, field, dir) {
  if (!Array.isArray(rows)) return [];
  const copy = [...rows];
  copy.sort((a, b) => {
    const av = String(a?.[field] ?? "").toLowerCase();
    const bv = String(b?.[field] ?? "").toLowerCase();
    if (av === bv) {
      const ai = Number.isFinite(a?.__sortIndex) ? a.__sortIndex : 0;
      const bi = Number.isFinite(b?.__sortIndex) ? b.__sortIndex : 0;
      return ai - bi;
    }
    const cmp = av > bv ? 1 : -1;
    return dir === "desc" ? -cmp : cmp;
  });
  return copy;
}

function normalizeCourierName(name) {
  const label = String(name || "").trim();
  if (!label) return "";
  return /^xpress\s*bees?$/i.test(label) ? "Xpress Bees" : label;
}

function riskPalette(flag) {
  if (flag === "HIGH") {
    return { bg: "rgba(239, 68, 68, 0.2)", color: "#fecaca", border: "rgba(239, 68, 68, 0.4)" };
  }
  if (flag === "MEDIUM") {
    return { bg: "rgba(245, 158, 11, 0.18)", color: "#fde68a", border: "rgba(245, 158, 11, 0.4)" };
  }
  return { bg: "rgba(148, 163, 184, 0.15)", color: brand.textMuted, border: PANEL_BORDER_STRONG };
}

export default function UserHistoryPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const initialSuborder = normalizeSuborderParam(params.get("suborder_id"));

  const [inputValue, setInputValue] = useState(initialSuborder);
  const [activeSuborder, setActiveSuborder] = useState(initialSuborder);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);

  const [activitySortBy, setActivitySortBy] = useState("suborder_id");
  const [activitySortDir, setActivitySortDir] = useState("asc");

  useEffect(() => {
    const next = normalizeSuborderParam(params.get("suborder_id"));
    setActiveSuborder(next);
    setInputValue(next);
  }, [params]);

  useEffect(() => {
    if (!activeSuborder) {
      setData(null);
      setError("");
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    setError("");
    setData(null);
    fetchUserHistoryBySuborder(activeSuborder)
      .then((snapshot) => {
        if (!alive) return;
        if (!snapshot) {
          setError("No history returned for this suborder.");
        } else {
          setData(snapshot);
        }
      })
      .catch((e) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [activeSuborder]);

  const handleSubmit = useCallback(
    (e) => {
      if (e && typeof e.preventDefault === "function") e.preventDefault();
      const clean = normalizeSuborderParam(inputValue);
      if (!clean || loading) return;
      if (clean === activeSuborder) return;
      setParams({ suborder_id: clean });
    },
    [activeSuborder, inputValue, loading, setParams],
  );

  const purchases = useMemo(
    () => (Array.isArray(data?.purchase_history) ? data.purchase_history : []),
    [data],
  );
  const returns = useMemo(
    () => (Array.isArray(data?.return_history) ? data.return_history : []),
    [data],
  );
  const unifiedRows = useMemo(() => {
    const purchaseBySuborder = new Map();
    purchases.forEach((item) => {
      const key = String(item?.suborder_id || "").trim();
      if (!key || purchaseBySuborder.has(key)) return;
      purchaseBySuborder.set(key, item);
    });

    const purchaseRows = purchases.map((item, idx) => {
      const suborder = String(item?.suborder_id || "").trim();
      return {
        ...item,
        suborder_id: suborder,
        courier_partner: normalizeCourierName(item?.courier_partner),
        status: "Purchased",
        type_of_return: "No return",
        return_reason: "No return",
        detailed_return_reason: "No return",
        row_type: "Purchase",
        __sortIndex: idx,
        __rowKey: `purchase-${suborder || "na"}-${idx}`,
      };
    });

    const returnRows = returns.map((item, idx) => {
      const suborder = String(item?.suborder_id || "").trim();
      const purchaseMatch = purchaseBySuborder.get(suborder) || {};
      return {
        ...item,
        suborder_id: suborder || String(purchaseMatch?.suborder_id || "").trim(),
        order_date: String(item?.order_date || purchaseMatch?.order_date || "").trim(),
        sku: String(item?.sku || purchaseMatch?.sku || "").trim(),
        payment_mode: String(item?.payment_mode || purchaseMatch?.payment_mode || "").trim(),
        courier_partner: normalizeCourierName(item?.courier_partner || purchaseMatch?.courier_partner),
        status: String(item?.status || item?.match_status || "Returned").trim(),
        type_of_return: String(item?.type_of_return || item?.sub_type || "Return").trim(),
        return_reason: String(item?.return_reason || "Not specified").trim(),
        detailed_return_reason: String(item?.detailed_return_reason || "Not specified").trim(),
        row_type: "Return",
        __sortIndex: purchaseRows.length + idx,
        __rowKey: `return-${suborder || "na"}-${item.awb_number || idx}`,
      };
    });
    return [...purchaseRows, ...returnRows];
  }, [purchases, returns]);
  const sortedActivityRows = useMemo(
    () => sortRows(unifiedRows, activitySortBy, activitySortDir),
    [unifiedRows, activitySortBy, activitySortDir],
  );

  const customer = data?.customer || null;
  const summary = data?.return_summary || null;
  const riskProfile = data?.risk_profile || null;
  const risk = riskPalette(riskProfile?.risk_flag);
  const totalPurchases = Number(data?.purchase_history_count ?? purchases.length) || 0;
  const returnTypeCounts = useMemo(() => {
    let rto = 0;
    let customerReturn = 0;
    for (const row of returns) {
      const kind = String(row?.type_of_return || "").toLowerCase();
      if (!kind) continue;
      if (kind.includes("customer return")) customerReturn += 1;
      if (kind.includes("rto") || kind.includes("courier return")) rto += 1;
    }
    return { rto, customerReturn };
  }, [returns]);

  const inputStyle = {
    flex: 1,
    minWidth: 0,
    borderRadius: 10,
    border: `1px solid ${PANEL_BORDER_STRONG}`,
    background: brand.bgInput,
    color: brand.text,
    fontFamily: font,
    fontSize: 14,
    padding: "10px 12px",
    outline: "none",
  };

  const buttonPrimaryStyle = {
    padding: "10px 16px",
    borderRadius: 10,
    border: "none",
    background: brand.gradientCta,
    color: "#fff",
    fontFamily: font,
    fontSize: 13,
    fontWeight: 700,
    cursor: loading || !inputValue.trim() ? "not-allowed" : "pointer",
    opacity: loading || !inputValue.trim() ? 0.6 : 1,
  };

  const backButtonStyle = {
    padding: "8px 12px",
    borderRadius: 10,
    border: `1px solid ${PANEL_BORDER_STRONG}`,
    background: "rgba(255,255,255,0.04)",
    color: brand.text,
    fontFamily: font,
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    textDecoration: "none",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
  };

  const selectStyle = {
    borderRadius: 8,
    border: `1px solid ${PANEL_BORDER_STRONG}`,
    background: brand.bgInput,
    color: brand.text,
    fontFamily: font,
    fontSize: 12,
    padding: "6px 10px",
    outline: "none",
  };

  const thStyle = {
    textAlign: "left",
    padding: "10px 12px",
    fontSize: 12,
    fontWeight: 700,
    color: brand.textMuted,
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  };

  const tdStyle = {
    padding: "10px 12px",
    fontSize: 13,
    color: brand.text,
    wordBreak: "break-word",
    verticalAlign: "top",
  };

  const hasActive = Boolean(activeSuborder);

  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: brand.bgPage,
        padding: "24px 20px 40px",
      }}
    >
      <div style={{ maxWidth: 1480, margin: "0 auto", display: "grid", gap: 16 }}>
        <div
          style={{
            borderRadius: 16,
            border: `1px solid ${brand.border}`,
            background: brand.bgCard,
            padding: "16px 18px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={() => {
                if (window.history.length > 1) navigate(-1);
                else navigate("/");
              }}
              style={backButtonStyle}
            >
              <span aria-hidden>←</span>
              <span>Back</span>
            </button>
            <div>
              <h1
                style={{
                  margin: 0,
                  color: brand.text,
                  fontFamily: font,
                  fontWeight: 800,
                  fontSize: 22,
                  letterSpacing: "-0.2px",
                }}
              >
                Customer history
              </h1>
              <p
                style={{
                  margin: "4px 0 0",
                  color: brand.textMuted,
                  fontFamily: font,
                  fontSize: 13,
                }}
              >
                Purchase and return activity for a Meesho buyer, fetched by suborder ID.
              </p>
            </div>
          </div>
          <Link to="/meesho" style={{ ...backButtonStyle, background: "rgba(255,255,255,0.02)" }}>
            Meesho workspace
          </Link>
        </div>

        <form
          onSubmit={handleSubmit}
          style={{
            borderRadius: 16,
            border: `1px solid ${brand.border}`,
            background: brand.bgCard,
            padding: 14,
            display: "flex",
            gap: 10,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <label
            htmlFor="user-history-suborder"
            style={{
              fontFamily: font,
              fontSize: 13,
              fontWeight: 700,
              color: brand.textMuted,
              minWidth: 120,
            }}
          >
            Suborder ID
          </label>
          <input
            id="user-history-suborder"
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Enter suborder ID"
            disabled={loading}
            style={inputStyle}
          />
          <button type="submit" disabled={loading || !inputValue.trim()} style={buttonPrimaryStyle}>
            {loading ? "Loading..." : "See history"}
          </button>
        </form>

        {!hasActive && !loading ? (
          <div
            style={{
              borderRadius: 16,
              border: `1px dashed ${PANEL_BORDER_STRONG}`,
              background: PANEL_BG,
              padding: "28px 20px",
              color: brand.textMuted,
              fontFamily: font,
              fontSize: 14,
              textAlign: "center",
            }}
          >
            Enter a suborder ID above to view the customer's full purchase and return history.
          </div>
        ) : null}

        {loading ? (
          <div
            style={{
              borderRadius: 16,
              border: `1px solid ${brand.border}`,
              background: brand.bgCard,
              padding: "28px 20px",
              color: brand.textMuted,
              fontFamily: font,
              fontSize: 14,
              textAlign: "center",
            }}
          >
            Loading history for suborder{" "}
            <strong style={{ color: brand.text }}>{activeSuborder}</strong>...
          </div>
        ) : null}

        {!loading && error ? (
          <div
            style={{
              borderRadius: 16,
              border: "1px solid rgba(239, 68, 68, 0.35)",
              background: "rgba(239, 68, 68, 0.08)",
              padding: "16px 18px",
              color: "#fca5a5",
              fontFamily: font,
              fontSize: 14,
            }}
          >
            {error}
          </div>
        ) : null}

        {!loading && !error && hasActive && !data ? (
          <div
            style={{
              borderRadius: 16,
              border: `1px solid ${brand.border}`,
              background: brand.bgCard,
              padding: "22px 20px",
              color: brand.textMuted,
              fontFamily: font,
              fontSize: 14,
              textAlign: "center",
            }}
          >
            No history found for suborder{" "}
            <strong style={{ color: brand.text }}>{activeSuborder}</strong>.
          </div>
        ) : null}

        {!loading && !error && data ? (
          <>
            <div
              style={{
                borderRadius: 16,
                border: `1px solid ${HISTORY_GREEN_BORDER}`,
                background: HISTORY_GREEN_BG,
                padding: "18px 20px",
                display: "grid",
                gridTemplateColumns: "minmax(260px, 1.4fr) minmax(220px, 1fr) minmax(220px, 1fr)",
                gap: 18,
              }}
            >
              <div>
                <div
                  style={{
                    color: brand.textDim,
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                  }}
                >
                  Customer
                </div>
                <div style={{ color: brand.text, fontSize: 18, fontWeight: 800, marginTop: 4 }}>
                  {customer?.name || "(Name unavailable)"}
                </div>
                <div style={{ color: brand.textMuted, fontSize: 13, marginTop: 4 }}>
                  {[customer?.address_1, customer?.district, customer?.state, customer?.pincode]
                    .filter(Boolean)
                    .join(", ") || "-"}
                </div>
                {customer?.phone_no ? (
                  <div style={{ color: brand.textMuted, fontSize: 13, marginTop: 4 }}>
                    Phone: {customer.phone_no}
                  </div>
                ) : null}
              </div>
              <div>
                <div
                  style={{
                    color: brand.textDim,
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                  }}
                >
                  Activity
                </div>
                <div style={{ color: brand.text, fontSize: 15, fontWeight: 700, marginTop: 6 }}>
                  Total Purchase: {totalPurchases}
                </div>
                <div style={{ color: brand.text, fontSize: 15, fontWeight: 700, marginTop: 2 }}>
                  RTO: {returnTypeCounts.rto}
                </div>
                <div style={{ color: brand.text, fontSize: 15, fontWeight: 700, marginTop: 2 }}>
                  Customer Return: {returnTypeCounts.customerReturn}
                </div>
                {summary && summary.has_return_analysis === false ? (
                  <div
                    style={{
                      color: brand.textDim,
                      fontSize: 12,
                      marginTop: 4,
                      fontStyle: "italic",
                    }}
                  >
                    Run a return analysis to populate detailed return rows.
                  </div>
                ) : null}
              </div>
              <div>
                <div
                  style={{
                    color: brand.textDim,
                    fontSize: 11,
                    fontWeight: 700,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                  }}
                >
                  Risk profile
                </div>
                {riskProfile ? (
                  <div
                    style={{
                      marginTop: 6,
                      padding: "10px 12px",
                      borderRadius: 10,
                      background: risk.bg,
                      border: `1px solid ${risk.border}`,
                      color: risk.color,
                      fontSize: 13,
                      fontWeight: 700,
                    }}
                  >
                    <div style={{ fontSize: 15 }}>{riskProfile.risk_flag || "LOW"}</div>
                    <div style={{ fontWeight: 600, marginTop: 4 }}>
                      Score: {Number(riskProfile.risk_score || 0).toFixed(2)} · Hits:{" "}
                      {riskProfile.hit_count || 0}
                    </div>
                  </div>
                ) : (
                  <div style={{ color: brand.textMuted, fontSize: 13, marginTop: 6 }}>
                    No risk profile available.
                  </div>
                )}
              </div>
            </div>

            <section
              style={{
                borderRadius: 16,
                border: `1px solid ${HISTORY_GREEN_BORDER}`,
                background: HISTORY_GREEN_BG,
                padding: "16px 16px 10px",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  flexWrap: "wrap",
                  gap: 10,
                  marginBottom: 10,
                }}
              >
                <h2
                  style={{
                    margin: 0,
                    color: brand.text,
                    fontFamily: font,
                    fontWeight: 800,
                    fontSize: 16,
                  }}
                >
                  Customer activity history ({sortedActivityRows.length})
                </h2>
              </div>
              <div
                style={{
                  borderRadius: 12,
                  border: `1px solid ${HISTORY_GREEN_BORDER}`,
                  overflow: "hidden",
                }}
              >
                <div style={{ maxHeight: 520, overflow: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse" }}>
                    <thead
                      style={{
                        position: "sticky",
                        top: 0,
                        background: HISTORY_GREEN_HEAD,
                        backdropFilter: "blur(4px)",
                      }}
                    >
                      <tr>
                        <th style={thStyle}>Type</th>
                        <th style={thStyle}>Suborder</th>
                        <th style={thStyle}>Print date</th>
                        <th style={{ ...thStyle, minWidth: 170 }}>SKU</th>
                        <th style={thStyle}>Payment</th>
                        <th style={thStyle}>Courier</th>
                        <th style={thStyle}>Return type</th>
                        <th style={thStyle}>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedActivityRows.length === 0 ? (
                        <tr>
                          <td
                            colSpan={8}
                            style={{ ...tdStyle, textAlign: "center", color: brand.textMuted }}
                          >
                            {summary && summary.has_return_analysis === false
                              ? "Run a return analysis upload to populate detailed return rows."
                              : "No activity rows found for this customer."}
                          </td>
                        </tr>
                      ) : (
                        sortedActivityRows.map((item, idx) => (
                          <tr
                            key={item.__rowKey || `${item.suborder_id || "row"}-${idx}`}
                            style={{ borderTop: idx === 0 ? "none" : HISTORY_GREEN_DIVIDER }}
                          >
                            <td style={tdStyle}>
                              <span
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  padding: "2px 8px",
                                  borderRadius: 999,
                                  border:
                                    item.row_type === "Return"
                                      ? "1px solid rgba(245, 158, 11, 0.4)"
                                      : `1px solid ${PANEL_BORDER_STRONG}`,
                                  background:
                                    item.row_type === "Return"
                                      ? "rgba(245, 158, 11, 0.18)"
                                      : "rgba(148, 163, 184, 0.16)",
                                  color:
                                    item.row_type === "Return" ? "#fde68a" : brand.textMuted,
                                  fontSize: 11,
                                  fontWeight: 700,
                                  letterSpacing: "0.02em",
                                  textTransform: "uppercase",
                                }}
                              >
                                {item.row_type}
                              </span>
                            </td>
                            <td style={tdStyle}>{item.suborder_id || "-"}</td>
                            <td style={tdStyle}>{item.order_date || "-"}</td>
                            <td
                              style={{
                                ...tdStyle,
                                minWidth: 170,
                                whiteSpace: "normal",
                                overflowWrap: "anywhere",
                              }}
                            >
                              {item.sku || "-"}
                            </td>
                            <td style={tdStyle}>{item.payment_mode || "-"}</td>
                            <td style={tdStyle}>{item.courier_partner || "-"}</td>
                            <td style={tdStyle}>{item.type_of_return || "-"}</td>
                            <td style={tdStyle}>{item.return_reason || "-"}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
