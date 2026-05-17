import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { brand, font } from "../theme/brandTheme.js";
import { GridIcon } from "../components/icons.jsx";

export default function ProfilePage() {
  const { user, updateProfile } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");
    setSaved(false);
    if (!name.trim()) {
      setError("Please enter a display name.");
      return;
    }
    try {
      updateProfile({ name: name.trim() });
      setSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save.");
    }
  };

  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: brand.bgPage,
        padding: "28px 24px 48px",
        fontFamily: font,
        color: brand.text,
      }}
    >
      <div style={{ maxWidth: 520, margin: "0 auto" }}>
        <p
          style={{
            margin: "0 0 8px",
            fontSize: 12,
            fontWeight: 700,
            color: brand.accentPink,
            letterSpacing: "0.08em",
          }}
        >
          ACCOUNT
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
          Edit profile
        </h1>
        <p style={{ margin: "0 0 28px", fontSize: 15, color: brand.textMuted, lineHeight: 1.55 }}>
          Update how your name appears in the app. Email cannot be changed here.
        </p>

        <form
          onSubmit={handleSubmit}
          style={{
            background: brand.bgCard,
            borderRadius: 18,
            border: `1px solid ${brand.border}`,
            padding: "28px 24px",
            boxShadow: `inset 0 1px 0 rgba(255,255,255,0.05)`,
          }}
        >
          <label style={{ display: "block", fontSize: 12, fontWeight: 700, color: brand.textDim, marginBottom: 8 }}>
            Display name
          </label>
          <input
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setSaved(false);
            }}
            style={{
              width: "100%",
              boxSizing: "border-box",
              marginBottom: 20,
              padding: "12px 14px",
              borderRadius: 12,
              border: `1px solid ${brand.border}`,
              background: brand.bgInput,
              color: brand.text,
              fontSize: 15,
              fontFamily: font,
              outline: "none",
            }}
          />

          <label style={{ display: "block", fontSize: 12, fontWeight: 700, color: brand.textDim, marginBottom: 8 }}>
            Email
          </label>
          <input
            value={user?.email ?? ""}
            readOnly
            style={{
              width: "100%",
              boxSizing: "border-box",
              marginBottom: 22,
              padding: "12px 14px",
              borderRadius: 12,
              border: `1px solid ${brand.border}`,
              background: "rgba(255,255,255,0.03)",
              color: brand.textMuted,
              fontSize: 15,
              fontFamily: font,
            }}
          />

          {error ? (
            <p style={{ margin: "0 0 14px", fontSize: 14, color: "#f87171", fontWeight: 600 }}>{error}</p>
          ) : null}
          {saved ? (
            <p style={{ margin: "0 0 14px", fontSize: 14, color: "#4ade80", fontWeight: 600 }}>Profile saved.</p>
          ) : null}

          <button
            type="submit"
            style={{
              padding: "12px 22px",
              borderRadius: 12,
              border: "none",
              background: brand.gradientCta,
              color: "#fff",
              fontSize: 15,
              fontWeight: 700,
              cursor: "pointer",
              fontFamily: font,
            }}
          >
            Save changes
          </button>
        </form>

        <Link
          to="/"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            marginTop: 24,
            fontSize: 14,
            fontWeight: 600,
            color: brand.accentPurple,
            textDecoration: "none",
          }}
        >
          <span style={{ display: "flex", opacity: 0.9 }}>
            <GridIcon />
          </span>
          Back to home
        </Link>
      </div>
    </div>
  );
}
