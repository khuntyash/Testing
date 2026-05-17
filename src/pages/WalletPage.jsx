import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useWallet } from "../wallet/WalletContext.jsx";
import CoinIcon from "../components/CoinIcon.jsx";
import { brand, font, homeHeroBackground } from "../theme/brandTheme.js";

function formatTs(ts) {
  try {
    return new Date(ts).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return "";
  }
}

export default function WalletPage() {
  const { balance, transactions, refreshWallet } = useWallet();
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState("");

  useEffect(() => {
    let alive = true;
    setRefreshing(true);
    setRefreshError("");
    refreshWallet()
      .catch((err) => {
        if (!alive) return;
        setRefreshError(err instanceof Error ? err.message : "Could not refresh wallet.");
      })
      .finally(() => {
        if (!alive) return;
        setRefreshing(false);
      });
    return () => {
      alive = false;
    };
  }, [refreshWallet]);

  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: homeHeroBackground,
        padding: "28px 24px 48px",
        fontFamily: font,
        color: brand.text,
      }}
    >
      <div style={{ maxWidth: 880, margin: "0 auto" }}>
        <div style={{ marginBottom: 14 }}>
          <Link
            to="/meesho"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              fontSize: 13,
              fontWeight: 600,
              color: "#cbd5e1",
              fontFamily: font,
              textDecoration: "none",
              padding: "6px 12px",
              borderRadius: 10,
              border: "1px solid rgba(148, 163, 184, 0.18)",
              background: "rgba(15, 23, 42, 0.45)",
              boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
              whiteSpace: "nowrap",
            }}
            title="Back to crop workspace"
          >
            <span aria-hidden>←</span> Back
          </Link>
        </div>
        <p
          style={{
            margin: "0 0 8px",
            fontSize: 12,
            fontWeight: 700,
            color: brand.accentPurple,
            letterSpacing: "0.08em",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <CoinIcon size={18} alt="" />
          PREMIUM · COINS
        </p>
        <h1
          style={{
            margin: "0 0 10px",
            fontSize: "clamp(22px, 3vw, 28px)",
            fontWeight: 800,
            color: brand.text,
            letterSpacing: "-0.5px",
          }}
        >
          Wallet
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <button
            type="button"
            onClick={() => {
              setRefreshing(true);
              setRefreshError("");
              refreshWallet()
                .catch((err) => {
                  setRefreshError(err instanceof Error ? err.message : "Could not refresh wallet.");
                })
                .finally(() => setRefreshing(false));
            }}
            disabled={refreshing}
            style={{
              borderRadius: 10,
              border: `1px solid ${brand.border}`,
              background: "rgba(15, 23, 42, 0.45)",
              color: brand.text,
              fontFamily: font,
              fontSize: 12.5,
              fontWeight: 700,
              padding: "7px 12px",
              cursor: refreshing ? "not-allowed" : "pointer",
            }}
          >
            {refreshing ? "Refreshing..." : "Refresh wallet"}
          </button>
          {refreshError ? (
            <span style={{ color: "#fca5a5", fontFamily: font, fontSize: 12.5 }}>{refreshError}</span>
          ) : null}
        </div>
        <p style={{ margin: "0 0 28px", fontSize: 15, color: brand.textMuted, lineHeight: 1.55, maxWidth: 560 }}>
          Wallet credits are admin-managed. You can view your balance and transaction history here, and
          premium crop billing deducts coins per output label when premium options are enabled.
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 20,
            marginBottom: 36,
          }}
        >
          <div
            style={{
              background: `linear-gradient(135deg, rgba(99,102,241,0.25) 0%, rgba(15,23,42,0.95) 100%)`,
              color: "#fff",
              borderRadius: 18,
              padding: "24px 22px",
              border: `1px solid ${brand.border}`,
              boxShadow: `inset 0 1px 0 rgba(255,255,255,0.06)`,
            }}
          >
            <div style={{ fontSize: 12, fontWeight: 700, opacity: 0.85, letterSpacing: "0.08em" }}>
              CURRENT BALANCE
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                marginTop: 8,
              }}
            >
              <CoinIcon size={44} alt="" />
              <div style={{ fontSize: 42, fontWeight: 800, letterSpacing: "-1px", lineHeight: 1 }}>
                {balance}
                <span style={{ fontSize: 18, fontWeight: 600, marginLeft: 8, opacity: 0.9 }}>coins</span>
              </div>
            </div>
            <Link
              to="/"
              style={{
                display: "inline-block",
                marginTop: 18,
                fontSize: 13,
                fontWeight: 600,
                color: brand.accentBlue,
                textDecoration: "none",
              }}
            >
              ← Back to dashboard
            </Link>
          </div>

          <div
            style={{
              background: brand.bgCard,
              backdropFilter: "blur(12px)",
              borderRadius: 18,
              padding: "22px 20px",
              border: `1px solid ${brand.border}`,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 800, color: brand.text, marginBottom: 10 }}>
              How credits are managed
            </div>
            <div style={{ fontSize: 13.5, color: brand.textMuted, lineHeight: 1.6 }}>
              Only admins can add wallet coins.
              <br />
              If your balance is low, contact an admin to top up your account.
              <br />
              This page remains read-only for regular users.
            </div>
          </div>
        </div>

        <div
          style={{
            background: brand.bgCard,
            backdropFilter: "blur(12px)",
            borderRadius: 18,
            border: `1px solid ${brand.border}`,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "16px 20px",
              borderBottom: `1px solid ${brand.border}`,
              fontWeight: 800,
              fontSize: 15,
              color: brand.text,
            }}
          >
            Transaction history
          </div>
          {transactions.length === 0 ? (
            <p style={{ padding: "24px 20px", margin: 0, color: brand.textDim, fontSize: 14 }}>
              No transactions yet. Admin credits and premium usage will appear here.
            </p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13, color: brand.textMuted }}>
                <thead>
                  <tr style={{ background: "rgba(255,255,255,0.04)", textAlign: "left" }}>
                    <th style={{ padding: "10px 16px", fontWeight: 700, color: brand.textDim }}>When</th>
                    <th style={{ padding: "10px 16px", fontWeight: 700, color: brand.textDim }}>Type</th>
                    <th style={{ padding: "10px 16px", fontWeight: 700, color: brand.textDim }}>Change</th>
                    <th style={{ padding: "10px 16px", fontWeight: 700, color: brand.textDim }}>Balance after</th>
                    <th style={{ padding: "10px 16px", fontWeight: 700, color: brand.textDim }}>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {transactions.map((tx) => (
                    <tr key={tx.id} style={{ borderTop: `1px solid ${brand.border}` }}>
                      <td style={{ padding: "12px 16px", color: brand.textMuted, whiteSpace: "nowrap" }}>
                        {formatTs(tx.ts)}
                      </td>
                      <td style={{ padding: "12px 16px", textTransform: "capitalize", color: brand.text }}>
                        {tx.type}
                      </td>
                      <td
                        style={{
                          padding: "12px 16px",
                          fontWeight: 700,
                          color: tx.delta >= 0 ? "#4ade80" : "#f87171",
                        }}
                      >
                        {tx.delta >= 0 ? "+" : ""}
                        {tx.delta}
                      </td>
                      <td style={{ padding: "12px 16px", fontWeight: 600, color: brand.text }}>{tx.balanceAfter}</td>
                      <td style={{ padding: "12px 16px", color: brand.textMuted, maxWidth: 320 }}>{tx.label}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
