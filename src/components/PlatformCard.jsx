import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PlatformLogo from "./PlatformLogo.jsx";
import { ScissorsIcon } from "./icons.jsx";

const BTN_BLUE = "#2563EB";

export default function PlatformCard({ p }) {
  const [hov, setHov] = useState(false);
  const navigate = useNavigate();

  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: "#fff",
        border: "1px solid #E9ECF2",
        borderRadius: 16,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        textAlign: "left",
        transition: "transform 0.22s cubic-bezier(0.16,1,0.3,1), box-shadow 0.22s ease",
        transform: hov ? "translateY(-4px)" : "translateY(0)",
        boxShadow: hov ? "0 12px 36px rgba(15, 23, 42, 0.12)" : "0 4px 20px rgba(15, 23, 42, 0.06)",
      }}
    >
      <div
        style={{
          background: "linear-gradient(180deg, #E8EDF3 0%, #F8FAFC 55%, #FFFFFF 100%)",
          padding: "32px 24px",
          minHeight: 132,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {p.logo ? (
          <img
            src={p.logo}
            alt=""
            style={{
              maxWidth: "100%",
              maxHeight: 88,
              width: "auto",
              height: "auto",
              objectFit: "contain",
            }}
          />
        ) : (
          <PlatformLogo p={p} size={72} />
        )}
      </div>

      <div
        style={{
          padding: "22px 22px 24px",
          display: "flex",
          flexDirection: "column",
          flex: 1,
          gap: 14,
          fontFamily: "'Montserrat', sans-serif",
        }}
      >
        <h3
          style={{
            margin: 0,
            fontWeight: 700,
            fontSize: 19,
            color: "#0F172A",
            letterSpacing: "-0.35px",
          }}
        >
          {p.name}
        </h3>
        <p
          style={{
            margin: 0,
            fontSize: 14,
            fontWeight: 400,
            color: "#475569",
            lineHeight: 1.55,
            flex: 1,
          }}
        >
          Effortlessly streamline your {p.name} shipping label preparation with our intuitive,
          one-click cropping and sorting solution.
        </p>
        <button
          type="button"
          onClick={() => navigate(`/${p.id}`)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 10,
            width: "100%",
            padding: "12px 16px",
            borderRadius: 10,
            border: "none",
            cursor: "pointer",
            background: BTN_BLUE,
            color: "#fff",
            fontFamily: "'Montserrat', sans-serif",
            fontWeight: 700,
            fontSize: 14,
            letterSpacing: "-0.2px",
            boxShadow: "0 4px 16px rgba(37, 99, 235, 0.38)",
            transition: "background 0.15s, transform 0.15s, box-shadow 0.15s",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "#1D4ED8";
            e.currentTarget.style.boxShadow = "0 6px 20px rgba(37, 99, 235, 0.45)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = BTN_BLUE;
            e.currentTarget.style.boxShadow = "0 4px 16px rgba(37, 99, 235, 0.38)";
          }}
        >
          <ScissorsIcon size={20} color="#fff" />
          Crop {p.name} Labels
        </button>
      </div>
    </div>
  );
}
