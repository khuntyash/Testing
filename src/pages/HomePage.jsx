import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import { PLATFORMS } from "../constants/platforms.js";
import CoinIcon from "../components/CoinIcon.jsx";
import { PREMIUM_CROP_COIN_COST_PER_LABEL } from "../wallet/coinConfig.js";
import { useWallet } from "../wallet/WalletContext.jsx";
import { PLATFORM_CARD_NEON, brand, font, gridOverlayStyle, homeHeroBackground } from "../theme/brandTheme.js";

function FeatureIconLightning() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M13 2L3 14h8l-1 8 10-12h-8l1-8z"
        stroke={brand.accentPurple}
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="rgba(167,139,250,0.15)"
      />
    </svg>
  );
}

function FeatureIconCube() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 2l8 4v8l-8 4-8-4V6l8-4z"
        stroke={brand.accentBlue}
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="rgba(96,165,250,0.12)"
      />
    </svg>
  );
}

function FeatureIconPin() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 21s7-4.35 7-11a7 7 0 10-14 0c0 6.65 7 11 7 11z"
        stroke={brand.accentPink}
        strokeWidth="1.5"
        fill="rgba(244,114,182,0.12)"
      />
      <circle cx="12" cy="10" r="2" fill={brand.accentPink} />
    </svg>
  );
}

function FeatureIconShield() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"
        stroke={brand.accentCyan}
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="rgba(34,211,238,0.1)"
      />
    </svg>
  );
}

const features = [
  {
    title: "Instant label generation",
    desc: "Crop and sort in one flow.",
    Icon: FeatureIconLightning,
  },
  {
    title: "Multi-platform support",
    desc: "Meesho & Flipkart today.",
    Icon: FeatureIconCube,
  },
  {
    title: "Real-time tracking",
    desc: "Coin wallet & history.",
    Icon: FeatureIconPin,
  },
  {
    title: "Secure & reliable",
    desc: "Your PDFs stay in-browser.",
    Icon: FeatureIconShield,
  },
];

function getBotReply(message) {
  const text = (message || "").toLowerCase();
  if (text.includes("coin") || text.includes("wallet")) {
    return `You can check your coin balance from Wallet. Premium crop features are billed at ${PREMIUM_CROP_COIN_COST_PER_LABEL} coin per output label, and admins manage wallet top-ups.`;
  }
  if (text.includes("meesho")) {
    return "To crop Meesho labels, open the Meesho workspace from homepage, upload PDFs, pick sort/layout, then process.";
  }
  if (text.includes("flipkart")) {
    return "For Flipkart, open Flipkart workspace, upload PDFs, and run crop. Sorting is configured in the Sort by panel.";
  }
  if (text.includes("login") || text.includes("signup") || text.includes("sign up")) {
    return "Use the Login/Signup pages from the header to access your account.";
  }
  if (text.includes("support") || text.includes("help")) {
    return "You can ask here, or email support@labelhub.app for manual help.";
  }
  return "I can help with Meesho/Flipkart crop flow, sorting, wallet, and account setup. What do you want to do?";
}

export default function HomePage() {
  const { user } = useAuth();
  const { balance } = useWallet();
  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([
    {
      role: "bot",
      text: "Hi! I am LabelHub assistant. Ask anything about crop, sorting, wallet, or setup.",
    },
  ]);
  const chatBodyRef = useRef(null);

  useEffect(() => {
    if (!chatOpen) return;
    if (chatBodyRef.current) {
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
    }
  }, [chatOpen, chatMessages]);

  const sendChat = () => {
    const trimmed = chatInput.trim();
    if (!trimmed) return;
    setChatMessages((prev) => [
      ...prev,
      { role: "user", text: trimmed },
      { role: "bot", text: getBotReply(trimmed) },
    ]);
    setChatInput("");
  };

  return (
    <div
      style={{
        position: "relative",
        minHeight: "calc(100vh - 64px)",
        background: homeHeroBackground,
        fontFamily: font,
        color: brand.text,
        overflow: "hidden",
      }}
    >
      <div style={gridOverlayStyle} />
      <div style={{ position: "relative", zIndex: 1, maxWidth: 1120, margin: "0 auto", padding: "40px 24px 100px" }}>
        <div style={{ textAlign: "center", marginBottom: 36 }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "8px 18px",
              borderRadius: 999,
              border: `1px solid ${brand.border}`,
              background: brand.bgCard,
              backdropFilter: "blur(10px)",
              fontSize: 12,
              fontWeight: 600,
              color: brand.textMuted,
              letterSpacing: "0.04em",
              marginBottom: 22,
            }}
          >
            <span style={{ color: brand.accentPink }}>✦</span>
            Smart labeling. Seamless selling.
          </div>

          <h1
            style={{
              margin: "0 auto 18px",
              maxWidth: 900,
              fontSize: "clamp(40px, 7vw, 72px)",
              fontWeight: 900,
              lineHeight: 0.95,
              letterSpacing: "-2.2px",
              color: brand.text,
              textShadow: "0 0 24px rgba(255,255,255,0.12), 0 0 48px rgba(96,165,250,0.16)",
            }}
          >
            Zero{" "}
            <span
              style={{
                background: brand.gradientHeadline,
                WebkitBackgroundClip: "text",
                WebkitTextFillColor: "transparent",
                backgroundClip: "text",
                filter: "drop-shadow(0 0 12px rgba(236,72,153,0.35))",
              }}
            >
              Label Cropper
            </span>
          </h1>

          <p
            style={{
              margin: "0 auto 12px",
              maxWidth: 560,
              fontSize: 16,
              lineHeight: 1.65,
              color: brand.textMuted,
            }}
          >
            Upload invoice PDFs, auto-crop shipping labels, sort by SKU or delivery partner — and use
            coins only when premium crop features are enabled.
          </p>
          <p
            style={{
              margin: 0,
              fontSize: 14,
              color: brand.textDim,
              display: "flex",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "6px 8px",
            }}
          >
            <span>
              Welcome back, <strong style={{ color: brand.text }}>{user?.name}</strong>
            </span>
            <span aria-hidden>·</span>
            <Link
              to="/wallet"
              style={{
                color: brand.accentBlue,
                fontWeight: 700,
                textDecoration: "none",
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <CoinIcon size={16} alt="" />
              {balance} coins
            </Link>
            <span aria-hidden>·</span>
            <span>
              Premium crops cost {PREMIUM_CROP_COIN_COST_PER_LABEL} coin per label
            </span>
          </p>
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
            gap: 28,
            maxWidth: 920,
            margin: "0 auto 48px",
          }}
        >
          {PLATFORMS.map((p) => {
            const neon = PLATFORM_CARD_NEON[p.id] ?? PLATFORM_CARD_NEON.meesho;
            const isMeesho = p.id === "meesho";
            const thumbSrc = p.homeThumbnail || p.logo;
            const thumbIsRaster = Boolean(p.homeThumbnail);
            return (
              <Link
                key={p.id}
                to={`/${p.id}`}
                style={{
                  textDecoration: "none",
                  color: "inherit",
                  borderRadius: 22,
                  border: `1.5px solid ${neon.border}`,
                  background: "rgba(255, 255, 255, 0.05)",
                  backdropFilter: "blur(14px)",
                  WebkitBackdropFilter: "blur(14px)",
                  padding: "26px 28px",
                  display: "flex",
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 22,
                  boxShadow: neon.glow,
                  transition: "transform 0.22s ease, box-shadow 0.22s ease",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.transform = "scale(1.03)";
                  e.currentTarget.style.boxShadow = neon.glowHover;
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.transform = "scale(1)";
                  e.currentTarget.style.boxShadow = neon.glow;
                }}
              >
                <div
                  style={{
                    width: 88,
                    height: 88,
                    borderRadius: 18,
                    background: neon.iconBg,
                    flexShrink: 0,
                    overflow: "hidden",
                    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.22)",
                  }}
                >
                  {thumbSrc ? (
                    <img
                      src={thumbSrc}
                      alt={`${p.name} logo`}
                      style={{
                        width: "100%",
                        height: "100%",
                        display: "block",
                        objectFit: thumbIsRaster ? "cover" : "contain",
                        objectPosition: "center",
                        filter: isMeesho ? "none" : "drop-shadow(0 1px 3px rgba(0,0,0,0.2))",
                      }}
                    />
                  ) : null}
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-start",
                    justifyContent: "center",
                    gap: 10,
                    minWidth: 0,
                    textAlign: "left",
                  }}
                >
                  <span
                    style={{
                      fontSize: "clamp(20px, 2.5vw, 24px)",
                      fontWeight: 800,
                      letterSpacing: "-0.5px",
                      color: "#ffffff",
                      lineHeight: 1.15,
                    }}
                  >
                    {p.name}
                  </span>
                  <span
                    style={{
                      fontSize: 15,
                      fontWeight: 500,
                      color: "rgba(248, 250, 252, 0.9)",
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                    }}
                  >
                    Get started <span aria-hidden style={{ fontSize: 18, fontWeight: 400 }}>→</span>
                  </span>
                  <span
                    style={{
                      fontSize: 12,
                      fontWeight: 500,
                      color: brand.textDim,
                      lineHeight: 1.4,
                      maxWidth: 280,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      flexWrap: "wrap",
                    }}
                  >
                    {isMeesho ? (
                      <>
                        <CoinIcon size={14} alt="" />
                        <span>Premium options enabled · billed per output label</span>
                      </>
                    ) : (
                      "Browser merge · no coins"
                    )}
                  </span>
                </div>
              </Link>
            );
          })}
        </div>

        <div
          id="feature-bar"
          style={{
            borderRadius: 16,
            border: `1px solid ${brand.border}`,
            background: "rgba(12, 14, 20, 0.75)",
            backdropFilter: "blur(12px)",
            padding: "20px 16px",
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
            gap: 20,
          }}
        >
          {features.map(({ title, desc, Icon }) => (
            <div
              key={title}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 12,
                padding: "4px 8px",
              }}
            >
              <div style={{ flexShrink: 0, marginTop: 2 }}>
                <Icon />
              </div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14, color: brand.text, marginBottom: 4 }}>{title}</div>
                <div style={{ fontSize: 12, color: brand.textDim, lineHeight: 1.45 }}>{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {chatOpen && (
        <div
          style={{
            position: "fixed",
            right: 22,
            bottom: 84,
            width: "min(360px, calc(100vw - 24px))",
            borderRadius: 14,
            border: `1px solid ${brand.border}`,
            background: "rgba(8, 10, 16, 0.95)",
            backdropFilter: "blur(10px)",
            boxShadow: "0 16px 38px rgba(0,0,0,0.45)",
            zIndex: 60,
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "10px 12px",
              borderBottom: `1px solid ${brand.border}`,
              background: "rgba(99, 102, 241, 0.16)",
              color: brand.text,
              fontSize: 13,
              fontWeight: 700,
            }}
          >
            LabelHub Chat Support
          </div>
          <div
            ref={chatBodyRef}
            style={{
              maxHeight: 280,
              overflowY: "auto",
              padding: 10,
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {chatMessages.map((m, idx) => (
              <div
                key={`${m.role}-${idx}`}
                style={{
                  alignSelf: m.role === "user" ? "flex-end" : "flex-start",
                  maxWidth: "82%",
                  padding: "8px 10px",
                  borderRadius: 10,
                  fontSize: 12.5,
                  lineHeight: 1.45,
                  color: brand.text,
                  border: `1px solid ${brand.border}`,
                  background:
                    m.role === "user"
                      ? "linear-gradient(120deg, rgba(168, 85, 247, 0.45), rgba(59, 130, 246, 0.4))"
                      : "rgba(255,255,255,0.05)",
                }}
              >
                {m.text}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, padding: 10, borderTop: `1px solid ${brand.border}` }}>
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") sendChat();
              }}
              placeholder="Type your message..."
              style={{
                flex: 1,
                minWidth: 0,
                borderRadius: 10,
                border: `1px solid ${brand.border}`,
                background: brand.bgInput,
                color: brand.text,
                fontSize: 12.5,
                padding: "9px 10px",
                outline: "none",
              }}
            />
            <button
              type="button"
              onClick={sendChat}
              style={{
                borderRadius: 10,
                border: `1px solid ${brand.border}`,
                background: brand.gradientCta,
                color: "#fff",
                fontWeight: 700,
                fontSize: 12,
                padding: "0 12px",
                cursor: "pointer",
              }}
            >
              Send
            </button>
          </div>
        </div>
      )}

      <button
        type="button"
        title="Open chat support"
        onClick={() => setChatOpen((prev) => !prev)}
        style={{
          position: "fixed",
          right: 22,
          bottom: 22,
          width: 52,
          height: 52,
          borderRadius: "50%",
          background: brand.gradientCta,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          boxShadow: "0 12px 32px rgba(99, 102, 241, 0.45)",
          textDecoration: "none",
          zIndex: 70,
          border: `1px solid ${brand.border}`,
          cursor: "pointer",
        }}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
          <path
            d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8.5z"
            stroke="#fff"
            strokeWidth="1.5"
            strokeLinejoin="round"
            fill="rgba(255,255,255,0.12)"
          />
        </svg>
      </button>
    </div>
  );
}
