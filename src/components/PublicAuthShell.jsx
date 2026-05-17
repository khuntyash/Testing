import { Link } from "react-router-dom";
import { brand, font, gridOverlayStyle, homeHeroBackground } from "../theme/brandTheme.js";
import { GridIcon } from "./icons.jsx";

/**
 * Shared dark hero background + minimal chrome for login / signup.
 */
export default function PublicAuthShell({ children }) {
  return (
    <div
      style={{
        position: "relative",
        minHeight: "100vh",
        background: homeHeroBackground,
        fontFamily: font,
        overflow: "hidden",
      }}
    >
      <div style={gridOverlayStyle} />
      <div
        style={{
          position: "relative",
          zIndex: 1,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 24px",
            borderBottom: `1px solid ${brand.border}`,
            background: "rgba(8, 8, 12, 0.6)",
            backdropFilter: "blur(12px)",
          }}
        >
          <Link
            to="/login"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              textDecoration: "none",
              color: brand.text,
            }}
          >
            <span
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: "linear-gradient(135deg, #7c3aed, #a855f7)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "#fff",
                boxShadow: `0 0 20px ${brand.borderGlow}`,
              }}
            >
              <GridIcon />
            </span>
            <span style={{ fontWeight: 800, fontSize: 17, letterSpacing: "-0.3px" }}>labelhub</span>
          </Link>
          <div style={{ fontSize: 12, color: brand.textMuted }}>Secure sign-in</div>
        </header>
        <div
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 24,
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
