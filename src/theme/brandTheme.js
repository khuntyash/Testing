/**
 * LabelHub dark SaaS palette — keep in sync across landing, auth, header, and app shell.
 */
export const font = "'Montserrat', sans-serif";

export const brand = {
  bgDeep: "#050508",
  bgPage: "#08080c",
  bgCard: "rgba(18, 20, 28, 0.78)",
  bgCardSolid: "#12151c",
  bgInput: "rgba(10, 12, 18, 0.9)",
  border: "rgba(148, 163, 184, 0.14)",
  borderGlow: "rgba(167, 139, 250, 0.45)",
  text: "#f8fafc",
  textMuted: "#94a3b8",
  textDim: "#64748b",
  accentPink: "#f472b6",
  accentPurple: "#a78bfa",
  accentBlue: "#60a5fa",
  accentCyan: "#22d3ee",
  gradientCta: "linear-gradient(120deg, #a855f7 0%, #6366f1 45%, #3b82f6 100%)",
  gradientHeadline: "linear-gradient(90deg, #e879f9 0%, #a78bfa 35%, #60a5fa 100%)",
  glowPink: "0 0 40px rgba(244, 114, 182, 0.35)",
  glowBlue: "0 0 40px rgba(96, 165, 250, 0.35)",
};

/** Home hero + sticky header on `/` — same stack so the bar blends with the page. */
export const homeHeroBackground = `radial-gradient(ellipse 90% 55% at 50% -15%, rgba(99, 102, 241, 0.22), transparent),
  radial-gradient(ellipse 50% 35% at 100% 20%, rgba(244, 114, 182, 0.1), transparent),
  ${brand.bgDeep}`;

/** Header / inner pages that sit on the flat app shell (wallet, workspace, profile). */
export const appShellFlatBackground = brand.bgPage;

/** Homepage platform mega-buttons — neon border + glass (reference UI). */
export const PLATFORM_CARD_NEON = {
  meesho: {
    border: "#ff2d95",
    glow:
      "0 0 16px rgba(255, 45, 149, 0.55), 0 0 40px rgba(255, 45, 149, 0.28), inset 0 0 12px rgba(255, 45, 149, 0.12)",
    glowHover:
      "0 0 22px rgba(255, 45, 149, 0.75), 0 0 52px rgba(255, 45, 149, 0.38), inset 0 0 14px rgba(255, 45, 149, 0.18)",
    iconBg: "linear-gradient(145deg, #ff4db8 0%, #e11d7a 45%, #b30c5a 100%)",
  },
  flipkart: {
    border: "#2d8eff",
    glow:
      "0 0 16px rgba(45, 142, 255, 0.5), 0 0 40px rgba(45, 142, 255, 0.25), inset 0 0 12px rgba(45, 142, 255, 0.12)",
    glowHover:
      "0 0 22px rgba(45, 142, 255, 0.72), 0 0 52px rgba(45, 142, 255, 0.35), inset 0 0 14px rgba(45, 142, 255, 0.18)",
    iconBg: "linear-gradient(145deg, #4da3ff 0%, #2d8eff 40%, #1565c0 100%)",
  },
};

export const gridOverlayStyle = {
  position: "absolute",
  inset: 0,
  pointerEvents: "none",
  opacity: 0.35,
  backgroundImage: `
    linear-gradient(rgba(139, 92, 246, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(139, 92, 246, 0.07) 1px, transparent 1px)
  `,
  backgroundSize: "44px 44px",
};

/** Meesho neon panel — used for the dedicated Meesho workspace view. */
export const MEESHO_NEON = {
  pink: "#ff2d95",
  pinkSoft: "#ff4db8",
  pinkDeep: "#b30c5a",
  panelBg:
    "radial-gradient(120% 80% at 0% 0%, rgba(255, 45, 149, 0.10), transparent 55%), radial-gradient(120% 80% at 100% 100%, rgba(99, 102, 241, 0.10), transparent 55%), rgba(14, 16, 22, 0.92)",
  panelBorder: "rgba(255, 45, 149, 0.32)",
  panelGlow:
    "0 0 0 1px rgba(255, 45, 149, 0.18), 0 30px 80px rgba(255, 45, 149, 0.18), inset 0 0 60px rgba(255, 45, 149, 0.05)",
  cardBg: "rgba(20, 22, 30, 0.85)",
  cardBorder: "rgba(255, 45, 149, 0.18)",
  cardBorderStrong: "rgba(255, 45, 149, 0.35)",
  ctaGradient:
    "linear-gradient(120deg, #ff2d95 0%, #b30c5a 45%, #6366f1 100%)",
  ctaGlow:
    "0 0 22px rgba(255, 45, 149, 0.55), 0 0 56px rgba(255, 45, 149, 0.32)",
  textHeadlineGradient:
    "linear-gradient(90deg, #ff8acc 0%, #ff2d95 45%, #a78bfa 100%)",
};

/** Subtle dotted/grid overlay tinted toward magenta — for the Meesho neon panel. */
export const meeshoNeonGridStyle = {
  position: "absolute",
  inset: 0,
  pointerEvents: "none",
  opacity: 0.55,
  backgroundImage: `
    linear-gradient(rgba(255, 45, 149, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 45, 149, 0.06) 1px, transparent 1px)
  `,
  backgroundSize: "48px 48px",
  maskImage:
    "radial-gradient(ellipse 70% 60% at 50% 0%, black 25%, transparent 80%)",
  WebkitMaskImage:
    "radial-gradient(ellipse 70% 60% at 50% 0%, black 25%, transparent 80%)",
};
