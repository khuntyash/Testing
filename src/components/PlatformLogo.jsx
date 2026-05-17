import { memo } from "react";

function PlatformLogo({ p, size = 44 }) {
  if (p.logo) {
    return (
      <img
        src={p.logo}
        alt=""
        style={{
          height: size,
          width: "auto",
          maxWidth: Math.round(size * 3),
          objectFit: "contain",
          flexShrink: 0,
          userSelect: "none",
          display: "block",
        }}
      />
    );
  }
  return (
    <div
      style={{
        width: size,
        height: size,
        borderRadius: Math.round(size * 0.26),
        background: p.color,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: "#fff",
        fontFamily: "'Montserrat', sans-serif",
        fontWeight: 800,
        fontSize: Math.round(size * 0.34),
        letterSpacing: "-0.5px",
        flexShrink: 0,
        userSelect: "none",
      }}
    >
      {p.abbr}
    </div>
  );
}

export default memo(PlatformLogo);
