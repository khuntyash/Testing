import { brand } from "../theme/brandTheme.js";
import { GridIcon } from "./icons.jsx";

export function FeatureTargetIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="8" stroke={brand.accentPink} strokeWidth="1.8" />
      <circle cx="12" cy="12" r="4" stroke={brand.accentPink} strokeWidth="1.8" />
      <circle cx="12" cy="12" r="1.8" fill={brand.accentPink} />
    </svg>
  );
}

export function FeatureStacksIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M12 4l8 4-8 4-8-4 8-4z" stroke={brand.accentPurple} strokeWidth="1.8" />
      <path d="M4 12l8 4 8-4" stroke={brand.accentPurple} strokeWidth="1.8" strokeLinecap="round" />
      <path d="M4 16l8 4 8-4" stroke={brand.accentPurple} strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export function FeatureLightningIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M13 2L5 13h6l-1 9 9-12h-6l1-8z"
        stroke={brand.accentPink}
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function FeatureShieldIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3l7 3v6c0 5.1-3.2 7.9-7 9-3.8-1.1-7-3.9-7-9V6l7-3z"
        stroke={brand.accentPurple}
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      <path d="M9.5 12.5l1.8 1.8 3.4-3.4" stroke={brand.accentPurple} strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

/** Default feature rows from the SignupPage 2 reference — shared by login and signup heroes. */
export const DEFAULT_AUTH_HERO_FEATURES = [
  { title: "Smart Detection", desc: "AI detects label areas accurately.", Icon: FeatureTargetIcon },
  { title: "Multi PDF Support", desc: "Merge and process multiple PDFs in one go.", Icon: FeatureStacksIcon },
  { title: "One Click Output", desc: "Get a single print-ready PDF instantly.", Icon: FeatureLightningIcon },
  { title: "Secure & Private", desc: "Your files stay private and encrypted.", Icon: FeatureShieldIcon },
];

const sectionStyle = {
  borderRadius: 22,
  border: `1px solid ${brand.border}`,
  background: `linear-gradient(135deg, ${brand.bgCardSolid} 0%, rgba(46, 16, 101, 0.32) 100%)`,
  boxShadow: `0 20px 60px rgba(0,0,0,0.35)`,
  padding: "28px 26px",
  minHeight: 640,
  position: "relative",
  overflow: "hidden",
};

const h1Style = {
  margin: "0 0 14px",
  fontWeight: 800,
  fontSize: "clamp(30px, 3.4vw, 44px)",
  color: "#f8fbff",
  letterSpacing: "-0.8px",
  lineHeight: 1.12,
  maxWidth: 560,
  textShadow: "0 2px 18px rgba(14, 22, 64, 0.45)",
};

const subStyle = {
  margin: "0 0 24px",
  fontSize: 22,
  color: "#c7cfdf",
  maxWidth: 560,
  lineHeight: 1.5,
};

/** Left-column marketing hero for public auth pages (signup, login). */
export default function AuthHero({
  headline,
  subhead,
  features = DEFAULT_AUTH_HERO_FEATURES,
  showLogo = true,
}) {
  return (
    <section style={sectionStyle}>
      <div
        style={{
          position: "absolute",
          right: -90,
          top: 80,
          width: 330,
          height: 330,
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(168, 85, 247, 0.36), transparent 65%)",
          filter: "blur(16px)",
        }}
      />
      {showLogo ? (
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 14,
            background: brand.gradientCta,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            boxShadow: brand.glowBlue,
            marginBottom: 22,
          }}
        >
          <GridIcon />
        </div>
      ) : null}
      <h1 style={h1Style}>{headline}</h1>
      <p style={subStyle}>{subhead}</p>

      <div style={{ display: "grid", gap: 16, maxWidth: 520 }}>
        {features.map(({ title, desc, Icon }) => (
          <div
            key={title}
            style={{
              display: "flex",
              gap: 14,
              alignItems: "flex-start",
              padding: "10px 0",
            }}
          >
            <div
              style={{
                width: 38,
                height: 38,
                borderRadius: 12,
                border: `1px solid ${brand.border}`,
                background: "rgba(255,255,255,0.04)",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "inset 0 0 18px rgba(167, 139, 250, 0.14)",
                flexShrink: 0,
              }}
            >
              <Icon />
            </div>
            <div>
              <div style={{ fontSize: 22, fontWeight: 700, color: "#d946ef", lineHeight: 1.2 }}>{title}</div>
              <div style={{ fontSize: 16, color: "#d2d9e8", marginTop: 4, lineHeight: 1.45 }}>{desc}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
