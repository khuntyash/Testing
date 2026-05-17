import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { useWallet } from "../wallet/WalletContext.jsx";
import { brand, font } from "../theme/brandTheme.js";
import CoinIcon from "./CoinIcon.jsx";

function initialsFromUser(user) {
  const n = (user?.name || user?.email || "?").trim();
  const parts = n.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  return n.slice(0, 2).toUpperCase();
}

const navLink = (active) => ({
  fontFamily: font,
  fontSize: 13,
  fontWeight: 600,
  textDecoration: "none",
  padding: "8px 12px",
  borderRadius: 8,
  color: active ? brand.accentPink : brand.textMuted,
  background: active ? "rgba(244, 114, 182, 0.12)" : "transparent",
  border: active ? `1px solid rgba(244, 114, 182, 0.35)` : "1px solid transparent",
  transition: "color 0.15s, background 0.15s",
});

export default function Header() {
  const { user, logout } = useAuth();
  const { balance } = useWallet();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef(null);

  useEffect(() => {
    if (!profileOpen) return;
    const onDoc = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) {
        setProfileOpen(false);
      }
    };
    const onKey = (e) => {
      if (e.key === "Escape") setProfileOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [profileOpen]);

  const headerBackground = pathname === "/" ? "rgba(8, 8, 12, 0.45)" : "rgba(8, 8, 12, 0.62)";

  const handleLogout = () => {
    setProfileOpen(false);
    logout();
    navigate("/login", { replace: true });
  };

  const menuItemBase = {
    display: "block",
    width: "100%",
    boxSizing: "border-box",
    padding: "10px 14px",
    borderRadius: 10,
    fontSize: 14,
    fontWeight: 600,
    fontFamily: font,
    textAlign: "left",
    border: "none",
    cursor: "pointer",
    textDecoration: "none",
    background: "transparent",
    color: brand.text,
  };

  return (
    <header
      className="lh-header"
      style={{
        minHeight: 64,
        background: headerBackground,
        backdropFilter: "blur(10px)",
        WebkitBackdropFilter: "blur(10px)",
        borderBottom: `1px solid ${brand.border}`,
        display: "flex",
        alignItems: "center",
        padding: "12px 20px",
        position: "sticky",
        top: 0,
        zIndex: 200,
        fontFamily: font,
      }}
    >
      <div
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
          flexWrap: "wrap",
        }}
      >
        <Link
          to="/"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 12,
            textDecoration: "none",
            color: brand.text,
            flexShrink: 0,
            order: 0,
          }}
        >
          <span
            style={{
              width: 50,
              height: 50,
              borderRadius: 14,
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              background:
                "linear-gradient(145deg, rgba(255,255,255,0.96) 0%, rgba(238,241,248,0.98) 100%)",
              border: "1px solid rgba(255,255,255,0.75)",
              boxShadow:
                "0 10px 26px rgba(0,0,0,0.34), 0 0 0 1px rgba(99,102,241,0.2), 0 0 22px rgba(56,189,248,0.2)",
              overflow: "hidden",
              transform: "translateY(-0.5px)",
            }}
          >
            <img
              src="/zero-label-logo-transparent.png"
              alt="Zero Label Cropper logo"
              style={{
                width: "82%",
                height: "82%",
                objectFit: "contain",
              }}
            />
          </span>
          <span
            style={{
              fontWeight: 900,
              fontSize: 20,
              letterSpacing: "-0.45px",
              lineHeight: 1,
              background: "linear-gradient(90deg, #f8fafc 0%, #c4b5fd 40%, #67e8f9 100%)",
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              color: "transparent",
              textShadow: "0 4px 16px rgba(125, 211, 252, 0.24)",
            }}
          >
            Zero E-commerce Solutions
          </span>
        </Link>

        <nav
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 4,
            flex: "1 1 auto",
            flexWrap: "wrap",
            minWidth: 0,
            order: 1,
          }}
        >
          {user?.isAdmin ? (
            <Link to="/admin" style={navLink(pathname === "/admin")}>
              Admin
            </Link>
          ) : null}
        </nav>

        <div
          ref={profileRef}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            flexShrink: 0,
            marginLeft: "auto",
            order: 2,
            position: "relative",
          }}
        >
          <Link
            to="/wallet"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 14px",
              borderRadius: 12,
              background: "rgba(167, 139, 250, 0.12)",
              border: `1px solid rgba(167, 139, 250, 0.35)`,
              textDecoration: "none",
              fontSize: 14,
              fontWeight: 700,
              color: brand.accentPurple,
            }}
          >
            <CoinIcon size={20} alt="" />
            {balance} coins
          </Link>

          <button
            type="button"
            aria-expanded={profileOpen}
            aria-haspopup="menu"
            onClick={() => setProfileOpen((o) => !o)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              padding: "6px 10px 6px 6px",
              borderRadius: 12,
              border: `1px solid ${brand.border}`,
              background: "rgba(255,255,255,0.05)",
              cursor: "pointer",
              fontFamily: font,
            }}
          >
            <span
              style={{
                width: 36,
                height: 36,
                borderRadius: "50%",
                background: brand.gradientCta,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#fff",
                fontSize: 12,
                fontWeight: 800,
                flexShrink: 0,
              }}
              aria-hidden
            >
              {initialsFromUser(user)}
            </span>
            <span style={{ textAlign: "left", minWidth: 0 }}>
              <span
                style={{
                  display: "block",
                  fontSize: 11,
                  color: brand.textDim,
                  fontWeight: 600,
                  lineHeight: 1.2,
                }}
              >
                My profile
              </span>
              <span
                style={{
                  display: "block",
                  fontSize: 13,
                  fontWeight: 700,
                  color: brand.text,
                  maxWidth: 140,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={user?.email}
              >
                {user?.name}
              </span>
            </span>
            <span style={{ fontSize: 10, color: brand.textMuted, marginLeft: 2 }} aria-hidden>
              {profileOpen ? "▲" : "▼"}
            </span>
          </button>

          {profileOpen ? (
            <div
              role="menu"
              style={{
                position: "absolute",
                top: "calc(100% + 8px)",
                right: 0,
                minWidth: 200,
                padding: 8,
                borderRadius: 14,
                border: `1px solid ${brand.border}`,
                background: "rgba(15, 15, 22, 0.98)",
                backdropFilter: "blur(12px)",
                boxShadow: "0 16px 48px rgba(0,0,0,0.45)",
                zIndex: 300,
              }}
            >
              <Link
                role="menuitem"
                to="/profile"
                onClick={() => setProfileOpen(false)}
                style={{
                  ...menuItemBase,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                }}
              >
                Edit profile
              </Link>
              <button
                type="button"
                role="menuitem"
                onClick={handleLogout}
                style={{
                  ...menuItemBase,
                  marginTop: 4,
                  color: brand.textMuted,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "rgba(248, 113, 113, 0.12)";
                  e.currentTarget.style.color = "#fca5a5";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.color = brand.textMuted;
                }}
              >
                Log out
              </button>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
