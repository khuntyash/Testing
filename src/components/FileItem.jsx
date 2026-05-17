import { memo } from "react";
import { CheckIcon } from "./icons.jsx";

function FileItem({ file, platform, onRemove, processed }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        background: "rgba(255,255,255,0.05)",
        border: "1px solid rgba(148, 163, 184, 0.14)",
        borderRadius: 10,
        padding: "9px 12px",
        transition: "border-color 0.2s",
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 8,
          flexShrink: 0,
          background: platform.bg,
          border: `1px solid ${platform.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "'Montserrat', sans-serif",
          fontWeight: 800,
          fontSize: 9,
          color: platform.color,
          letterSpacing: "0.3px",
        }}
      >
        PDF
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 500,
            color: "#e2e8f0",
            fontFamily: "'Montserrat', sans-serif",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {file.name}
        </div>
        <div style={{ fontSize: 11, color: "#94A3B8", fontFamily: "'Montserrat', sans-serif" }}>
          {(file.size / 1024).toFixed(1)} KB
        </div>
      </div>
      {processed ? (
        <div
          style={{
            width: 22,
            height: 22,
            borderRadius: "50%",
            background: "#16A34A",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flexShrink: 0,
          }}
        >
          <CheckIcon size={11} />
        </div>
      ) : (
        <button
          type="button"
          onClick={onRemove}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "#CBD5E1",
            fontSize: 15,
            padding: "2px 4px",
            lineHeight: 1,
            flexShrink: 0,
            borderRadius: 4,
          }}
        >
          ✕
        </button>
      )}
    </div>
  );
}

export default memo(FileItem);
