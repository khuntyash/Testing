import { memo, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { OUTPUT_LAYOUTS, PLATFORMS, SORT_OPTIONS } from "../constants/platforms.js";
import { MEESHO_NEON, brand, font, meeshoNeonGridStyle } from "../theme/brandTheme.js";
import { PREMIUM_CROP_COIN_COST_PER_LABEL } from "../wallet/coinConfig.js";
import CoinIcon from "./CoinIcon.jsx";
import FileItem from "./FileItem.jsx";
import { CheckIcon, UploadIcon } from "./icons.jsx";
import PlatformLogo from "./PlatformLogo.jsx";

// Keep Meesho palette fixed so Flipkart color overrides never leak into it.
const MEESHO_NEON_BASE = {
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
  ctaGradient: "linear-gradient(120deg, #ff2d95 0%, #b30c5a 45%, #6366f1 100%)",
  ctaGlow: "0 0 22px rgba(255, 45, 149, 0.55), 0 0 56px rgba(255, 45, 149, 0.32)",
  textHeadlineGradient: "linear-gradient(90deg, #ff8acc 0%, #ff2d95 45%, #a78bfa 100%)",
};
const FLIPKART_NEON = {
  pink: "#2d8eff",
  pinkSoft: "#7db8ff",
  pinkDeep: "#155fbe",
  panelBg:
    "radial-gradient(120% 80% at 0% 0%, rgba(45, 142, 255, 0.12), transparent 55%), radial-gradient(120% 80% at 100% 100%, rgba(37, 99, 235, 0.11), transparent 55%), rgba(14, 16, 22, 0.92)",
  panelBorder: "rgba(45, 142, 255, 0.34)",
  panelGlow:
    "0 0 0 1px rgba(45, 142, 255, 0.2), 0 30px 80px rgba(45, 142, 255, 0.18), inset 0 0 60px rgba(45, 142, 255, 0.05)",
  cardBorder: "rgba(45, 142, 255, 0.2)",
  cardBorderStrong: "rgba(45, 142, 255, 0.38)",
  ctaGradient: "linear-gradient(120deg, #2d8eff 0%, #155fbe 45%, #1d4ed8 100%)",
  ctaGlow: "0 0 22px rgba(45, 142, 255, 0.55), 0 0 56px rgba(45, 142, 255, 0.3)",
  textHeadlineGradient: "linear-gradient(90deg, #a8ceff 0%, #2d8eff 45%, #60a5fa 100%)",
};

function accent(alpha) {
  const hex = (MEESHO_NEON.pink || "").replace("#", "");
  const full =
    hex.length === 3
      ? hex
          .split("")
          .map((c) => c + c)
          .join("")
      : hex;
  const n = Number.parseInt(full || "ff2d95", 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function normalizeCourierName(name) {
  const label = String(name || "Unknown").trim() || "Unknown";
  return /^xpress\s*bees?$/i.test(label) ? "Xpress Bees" : label;
}

function sortCourierEntries(entries) {
  const preferredOrder = ["ValmoPlus", "Valmo", "Delhivery", "Shadowfax", "Xpress Bees"];
  const preferredIndex = new Map(preferredOrder.map((name, idx) => [name.toLowerCase(), idx]));
  entries.sort((a, b) => {
    const aIdx = preferredIndex.get(String(a[0] || "").toLowerCase());
    const bIdx = preferredIndex.get(String(b[0] || "").toLowerCase());
    if (aIdx !== undefined && bIdx !== undefined) return aIdx - bIdx;
    if (aIdx !== undefined) return -1;
    if (bIdx !== undefined) return 1;
    if (a[0] === "Unknown" && b[0] !== "Unknown") return 1;
    if (b[0] === "Unknown" && a[0] !== "Unknown") return -1;
    if (b[1] !== a[1]) return b[1] - a[1];
    return a[0].localeCompare(b[0]);
  });
}

function validatePincodeInput(raw) {
  const text = String(raw || "").trim();
  if (!text) return { state: "idle", validCount: 0, totalCount: 0, invalidPreview: [] };
  const tokens = text
    .replace(/\n/g, ",")
    .replace(/\|/g, ",")
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
  if (!tokens.length) return { state: "idle", validCount: 0, totalCount: 0, invalidPreview: [] };
  const invalid = tokens.filter((token) => !/^\d{6}$/.test(token));
  const invalidUnique = Array.from(new Set(invalid));
  return {
    state: invalid.length ? "invalid" : "valid",
    validCount: tokens.length - invalid.length,
    totalCount: tokens.length,
    invalidTokens: invalidUnique,
  };
}

function buildPincodeHighlightSegments(raw) {
  const text = String(raw || "");
  if (!text) return [];
  const parts = text.split(/([,\n|])/);
  const segments = [];
  parts.forEach((part) => {
    if (part === "," || part === "\n" || part === "|") {
      segments.push({ text: part, invalid: false });
      return;
    }
    if (!part) return;
    const leading = (part.match(/^\s*/) || [""])[0];
    const trailing = (part.match(/\s*$/) || [""])[0];
    const core = part.trim();
    if (leading) segments.push({ text: leading, invalid: false });
    if (core) {
      segments.push({ text: core, invalid: !/^\d{6}$/.test(core) });
    }
    if (trailing) segments.push({ text: trailing, invalid: false });
  });
  return segments;
}

/**
 * Highly-styled Meesho-only workspace UI. Receives all state and handlers from
 * `WorkspaceView` so functionality stays identical to the shared component.
 *
 * Wrapped in React.memo so the heavy SVG/grid layout only re-renders when
 * `p` or the `ws` props bag from WorkspaceView actually changes.
 */
function MeeshoNeonViewImpl({ p, ws }) {
  const isFlipkart = p.id === "flipkart";
  Object.assign(
    MEESHO_NEON,
    isFlipkart ? { ...MEESHO_NEON_BASE, ...FLIPKART_NEON } : MEESHO_NEON_BASE,
  );

  // Local-only memory of the most recently picked return-Excel filename so we
  // can surface "<file>.xlsx uploaded" feedback immediately, even before the
  // server task has confirmed acceptance.
  const [returnFileName, setReturnFileName] = useState("");

  const {
    files,
    filesRequireReselection,
    restoreWarning,
    hasFiles,
    drag,
    setDrag,
    addFiles,
    handleDrop,
    inputRef,
    outputLayout,
    setOutputLayout,
    sortBy,
    setSortBy,
    printDateTimeOnLabel,
    setPrintDateTimeOnLabel,
    multiOrderAtBottom,
    setMultiOrderAtBottom,
    separatePincodesEnabled,
    setSeparatePincodesEnabled,
    separatePincodes,
    setSeparatePincodes,
    detectSuspiciousBuyerEnabled,
    setDetectSuspiciousBuyerEnabled,
    suspiciousMarkerPreviewEnabled,
    setSuspiciousMarkerPreviewEnabled,
    separateMultiOrderEnabled,
    setSeparateMultiOrderEnabled,
    loyalCustomerEnabled,
    setLoyalCustomerEnabled,
    loyalCustomerPreviewEnabled,
    setLoyalCustomerPreviewEnabled,
    userHistorySuborderId,
    setUserHistorySuborderId,
    printCustomMessage,
    setPrintCustomMessage,
    customPrintMessage,
    setCustomPrintMessage,
    processing,
    processed,
    progress,
    cropProgressMessage,
    cropBillingMessage,
    outputPdfBytes,
    outputArtifactName,
    cropTaskSummary,
    mergeError,
    ocrProcessing,
    ocrError,
    ocrColumnPreset,
    setOcrColumnPreset,
    ocrCustomColumns,
    setOcrCustomColumns,
    ocrMaxWorkers,
    setOcrMaxWorkers,
    ocrTaskStatus,
    ocrProgress,
    ocrProgressMessage,
    returnAnalysisProcessing,
    returnAnalysisError,
    returnAnalysisTaskStatus,
    returnAnalysisProgress,
    returnAnalysisProgressMessage,
    returnAnalysisSummary,
    ocrPresetOptions,
    coinGateError,
    balance,
    handleProcess,
    handleDownloadPdf,
    handleGenerateOcrExcel,
    handleStartReturnAnalysis,
    returnInputRef,
    setMergeError,
    setOcrError,
    setCoinGateError,
    setFiles,
    setProcessed,
    setProcessing,
    setProgress,
    cropTaskId,
    setCropTaskId,
    setCropTaskStatus,
    setCropProgressMessage,
    clearActiveTask,
    setOutputPdfBytes,
    setOutputArtifactName,
    setOutputArtifactMime,
    setCropTaskSummary,
    setOcrTaskId,
    setOcrTaskStatus,
    setOcrProgress,
    setOcrProgressMessage,
    setReturnAnalysisTaskId,
    setReturnAnalysisTaskStatus,
    setReturnAnalysisProgress,
    setReturnAnalysisProgressMessage,
    setReturnAnalysisError,
    setReturnAnalysisSummary,
    layoutLabel,
    cropHistory,
    historyDownloadJobId,
    handleDownloadHistoryJob,
  } = ws;

  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: brand.bgPage,
        display: "flex",
        flexDirection: "column",
        fontFamily: font,
        color: brand.text,
      }}
    >
      <TopHeaderStrip p={p} />

      <div
        className="meesho-neon-outer"
        style={{
          flex: 1,
          padding: "22px 22px 32px",
          minHeight: 0,
        }}
      >
        <div
          className="meesho-neon-panel"
          style={{
            position: "relative",
            borderRadius: 24,
            border: `1.5px solid ${MEESHO_NEON.panelBorder}`,
            background: MEESHO_NEON.panelBg,
            boxShadow: MEESHO_NEON.panelGlow,
            overflow: "hidden",
            padding: "28px 28px 24px",
          }}
        >
          <div style={meeshoNeonGridStyle} />

          <NeonGlowAccent
            style={{
              top: -120,
              left: -120,
              width: 360,
              height: 360,
              background: `radial-gradient(circle, ${accent(0.35)}, transparent 60%)`,
            }}
          />
          <NeonGlowAccent
            style={{
              bottom: -160,
              right: -120,
              width: 380,
              height: 380,
              background: "radial-gradient(circle, rgba(99, 102, 241, 0.28), transparent 60%)",
            }}
          />

          <div
            className="meesho-neon-grid"
            style={{
              position: "relative",
              zIndex: 1,
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) 560px",
              gap: 20,
              alignItems: "start",
            }}
          >
            <MainColumn
              p={p}
              files={files}
              filesRequireReselection={filesRequireReselection}
              restoreWarning={restoreWarning}
              hasFiles={hasFiles}
              drag={drag}
              setDrag={setDrag}
              addFiles={addFiles}
              handleDrop={handleDrop}
              inputRef={inputRef}
              processing={processing}
              processed={processed}
              progress={progress}
              cropProgressMessage={cropProgressMessage}
              cropBillingMessage={cropBillingMessage}
              outputPdfBytes={outputPdfBytes}
              outputArtifactName={outputArtifactName}
              cropTaskSummary={cropTaskSummary}
              mergeError={mergeError}
              ocrProcessing={ocrProcessing}
              ocrError={ocrError}
              ocrColumnPreset={ocrColumnPreset}
              setOcrColumnPreset={setOcrColumnPreset}
              ocrCustomColumns={ocrCustomColumns}
              setOcrCustomColumns={setOcrCustomColumns}
              ocrMaxWorkers={ocrMaxWorkers}
              setOcrMaxWorkers={setOcrMaxWorkers}
              ocrTaskStatus={ocrTaskStatus}
              ocrProgress={ocrProgress}
              ocrProgressMessage={ocrProgressMessage}
              returnAnalysisProcessing={returnAnalysisProcessing}
              returnAnalysisError={returnAnalysisError}
              returnAnalysisTaskStatus={returnAnalysisTaskStatus}
              returnAnalysisProgress={returnAnalysisProgress}
              returnAnalysisProgressMessage={returnAnalysisProgressMessage}
              returnAnalysisSummary={returnAnalysisSummary}
              returnFileName={returnFileName}
              setReturnFileName={setReturnFileName}
              ocrPresetOptions={ocrPresetOptions}
              coinGateError={coinGateError}
              balance={balance}
              handleProcess={handleProcess}
              handleDownloadPdf={handleDownloadPdf}
              handleGenerateOcrExcel={handleGenerateOcrExcel}
              handleStartReturnAnalysis={handleStartReturnAnalysis}
              returnInputRef={returnInputRef}
              setMergeError={setMergeError}
              setOcrError={setOcrError}
              setCoinGateError={setCoinGateError}
              setFiles={setFiles}
              setProcessed={setProcessed}
              setProcessing={setProcessing}
              setProgress={setProgress}
              setOutputPdfBytes={setOutputPdfBytes}
              setOutputArtifactName={setOutputArtifactName}
              setOutputArtifactMime={setOutputArtifactMime}
              setCropTaskSummary={setCropTaskSummary}
              setOcrTaskId={setOcrTaskId}
              setOcrTaskStatus={setOcrTaskStatus}
              setOcrProgress={setOcrProgress}
              setOcrProgressMessage={setOcrProgressMessage}
              setReturnAnalysisTaskId={setReturnAnalysisTaskId}
              setReturnAnalysisTaskStatus={setReturnAnalysisTaskStatus}
              setReturnAnalysisProgress={setReturnAnalysisProgress}
              setReturnAnalysisProgressMessage={setReturnAnalysisProgressMessage}
              setReturnAnalysisError={setReturnAnalysisError}
              setReturnAnalysisSummary={setReturnAnalysisSummary}
              clearActiveTask={clearActiveTask}
              sortBy={sortBy}
              layoutLabel={layoutLabel}
              cropHistory={cropHistory}
              historyDownloadJobId={historyDownloadJobId}
              handleDownloadHistoryJob={handleDownloadHistoryJob}
            />

            <Sidebar
              p={p}
              outputLayout={outputLayout}
              setOutputLayout={setOutputLayout}
              sortBy={sortBy}
              setSortBy={setSortBy}
              printDateTimeOnLabel={printDateTimeOnLabel}
              setPrintDateTimeOnLabel={setPrintDateTimeOnLabel}
              multiOrderAtBottom={multiOrderAtBottom}
              setMultiOrderAtBottom={setMultiOrderAtBottom}
              separatePincodesEnabled={separatePincodesEnabled}
              setSeparatePincodesEnabled={setSeparatePincodesEnabled}
              separatePincodes={separatePincodes}
              setSeparatePincodes={setSeparatePincodes}
              detectSuspiciousBuyerEnabled={detectSuspiciousBuyerEnabled}
              setDetectSuspiciousBuyerEnabled={setDetectSuspiciousBuyerEnabled}
              suspiciousMarkerPreviewEnabled={suspiciousMarkerPreviewEnabled}
              setSuspiciousMarkerPreviewEnabled={setSuspiciousMarkerPreviewEnabled}
              separateMultiOrderEnabled={separateMultiOrderEnabled}
              setSeparateMultiOrderEnabled={setSeparateMultiOrderEnabled}
              loyalCustomerEnabled={loyalCustomerEnabled}
              setLoyalCustomerEnabled={setLoyalCustomerEnabled}
              loyalCustomerPreviewEnabled={loyalCustomerPreviewEnabled}
              setLoyalCustomerPreviewEnabled={setLoyalCustomerPreviewEnabled}
              userHistorySuborderId={userHistorySuborderId}
              setUserHistorySuborderId={setUserHistorySuborderId}
              balance={balance}
              cropTaskSummary={cropTaskSummary}
              onResetCourierTotals={() => {
                setCropTaskSummary((previous) => {
                  if (!previous || typeof previous !== "object") return null;
                  const next = { ...previous };
                  delete next.courier_counts;
                  delete next.courier_count_total;
                  delete next.courier_count_error;
                  return Object.keys(next).length ? next : null;
                });
              }}
            />
          </div>

          <FeatureStrip />

          <TipRow />
        </div>
      </div>

      <input
        ref={inputRef}
        type="file"
        accept=".pdf"
        multiple
        style={{ display: "none" }}
        onChange={(e) => {
          addFiles(e.target.files);
          e.target.value = "";
        }}
      />
      <input
        ref={returnInputRef}
        type="file"
        accept=".xlsx,.xls,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
        style={{ display: "none" }}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) {
            // Capture filename first so the UI shows "<file> uploaded" instantly,
            // even before the task POST has resolved.
            setReturnFileName(file.name || "Return Excel");
            handleStartReturnAnalysis(file);
          }
          e.target.value = "";
        }}
      />

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes meeshoNeonPulse {
          0%, 100% { box-shadow: 0 0 18px ${accent(0.45)}, 0 0 38px ${accent(0.22)}; }
          50% { box-shadow: 0 0 28px ${accent(0.7)}, 0 0 60px ${accent(0.38)}; }
        }
        @media (max-width: 1480px) {
          .meesho-neon-grid { grid-template-columns: minmax(0, 1fr) 500px !important; }
        }
        @media (max-width: 1320px) {
          .meesho-neon-grid { grid-template-columns: minmax(0, 1fr) 450px !important; }
          .meesho-sidebar-row { grid-template-columns: 1fr 1fr !important; }
        }
        @media (max-width: 1160px) {
          .meesho-neon-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 960px) {
          .meesho-upload-grid { grid-template-columns: 1fr !important; }
          .meesho-sidebar-row { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 720px) {
          .workspace-header-bar { grid-template-columns: 1fr !important; gap: 8px !important; padding: 10px 12px !important; }
          .workspace-header-nav { justify-content: flex-start !important; }
          .workspace-header-status { justify-content: flex-start !important; }
        }
        @media (max-width: 640px) {
          .workspace-header-nav a { font-size: 13px !important; }
        }
        @media (max-width: 580px) {
          .meesho-neon-outer { padding: 14px !important; }
          .meesho-neon-panel { padding: 20px 16px !important; border-radius: 18px !important; }
          .meesho-upload-grid { gap: 10px !important; }
          .meesho-feature-strip { grid-template-columns: 1fr 1fr !important; }
          .meesho-premium-balance-row { align-items: flex-start !important; }
          .meesho-premium-topup { margin-left: 0 !important; }
        }
      `}</style>
    </div>
  );
}

function TopHeaderStrip({ p }) {
  return (
    <div
      className="workspace-header-bar"
      style={{
        background: "linear-gradient(180deg, rgba(7, 10, 18, 0.96) 0%, rgba(6, 9, 16, 0.9) 100%)",
        borderBottom: "1px solid rgba(148, 163, 184, 0.14)",
        padding: "10px 16px",
        display: "grid",
        gridTemplateColumns: "auto minmax(0, 1fr) auto",
        alignItems: "center",
        gap: "8px 14px",
      }}
    >
      <div
        className="workspace-header-left"
        style={{ display: "flex", alignItems: "center", minWidth: 0 }}
      >
        <Link
          to="/"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 13,
            fontWeight: 600,
            color: "#cbd5e1",
            fontFamily: font,
            textDecoration: "none",
            padding: "8px 14px",
            borderRadius: 10,
            border: "2px solid rgba(148, 163, 184, 0.28)",
            background: "rgba(15, 23, 42, 0.45)",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
            whiteSpace: "nowrap",
          }}
        >
          <span aria-hidden>←</span> All platforms
        </Link>
      </div>

      <nav
        className="workspace-header-nav"
        aria-label="Switch platform cropper"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          minWidth: 0,
          overflowX: "auto",
          overflowY: "hidden",
          padding: "2px 2px",
          WebkitOverflowScrolling: "touch",
          scrollbarWidth: "thin",
        }}
      >
        {PLATFORMS.map((plat) => {
          const active = plat.id === p.id;
          const isMeesho = plat.id === "meesho";
          return (
            <Link
              key={plat.id}
              to={`/${plat.id}`}
              title={`${plat.name} cropper`}
              style={{
                flexShrink: 0,
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 14px 6px 9px",
                borderRadius: 999,
                textDecoration: "none",
                fontFamily: font,
                fontSize: 15,
                fontWeight: 700,
                color: "#f8fafc",
                border: active
                  ? isMeesho
                    ? "2px solid rgba(255, 45, 149, 0.78)"
                    : "2px solid rgba(45, 142, 255, 0.78)"
                  : "2px solid rgba(148, 163, 184, 0.28)",
                background: active
                  ? isMeesho
                    ? "linear-gradient(135deg, rgba(255, 45, 149, 0.28), rgba(168, 85, 247, 0.2))"
                    : "linear-gradient(135deg, rgba(45, 142, 255, 0.22), rgba(29, 78, 216, 0.2))"
                  : "rgba(15, 23, 42, 0.62)",
                boxShadow: active
                  ? isMeesho
                    ? "0 0 16px rgba(255, 45, 149, 0.34), inset 0 1px 0 rgba(255,255,255,0.1)"
                    : "0 0 16px rgba(45, 142, 255, 0.3), inset 0 1px 0 rgba(255,255,255,0.08)"
                  : "inset 0 1px 0 rgba(255,255,255,0.04)",
                transition: "background 0.15s, border-color 0.15s, box-shadow 0.15s",
                whiteSpace: "nowrap",
              }}
            >
              <span
                style={{
                  width: 20,
                  height: 20,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  overflow: "hidden",
                  borderRadius: 5,
                  background: "rgba(15, 23, 42, 0.55)",
                }}
              >
                {plat.homeThumbnail || plat.logo ? (
                  <img
                    src={plat.homeThumbnail || plat.logo}
                    alt={`${plat.name} logo`}
                    style={{
                      width: "100%",
                      height: "100%",
                      objectFit: "contain",
                      display: "block",
                    }}
                  />
                ) : (
                  <PlatformLogo p={plat} size={18} />
                )}
              </span>
              <span>{plat.name}</span>
            </Link>
          );
        })}
        <Link
          to="/my-dashboard"
          title="My dashboard"
          style={{
            flexShrink: 0,
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 14px",
            borderRadius: 999,
            textDecoration: "none",
            fontFamily: font,
            fontSize: 15,
            fontWeight: 700,
            color: "#f8fafc",
            border: "2px solid rgba(148, 163, 184, 0.3)",
            background: "rgba(15, 23, 42, 0.62)",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
            transition: "background 0.15s, border-color 0.15s, box-shadow 0.15s",
            whiteSpace: "nowrap",
          }}
        >
          My dashboard
        </Link>
      </nav>

      <div
        className="workspace-header-status"
        style={{ display: "flex", alignItems: "center", justifyContent: "flex-end" }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 7,
            fontSize: 13,
            fontWeight: 700,
            color: "#6ee7b7",
            fontFamily: font,
            padding: "8px 15px",
            borderRadius: 999,
            background: "linear-gradient(180deg, rgba(3, 56, 46, 0.84), rgba(4, 45, 40, 0.84))",
            border: "2px solid rgba(52, 211, 153, 0.5)",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), 0 0 12px rgba(16, 185, 129, 0.15)",
            whiteSpace: "nowrap",
          }}
        >
          <span
            aria-hidden
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#10b981",
              boxShadow: "0 0 10px #10b981",
            }}
          />
          Ready to upload
        </span>
      </div>
    </div>
  );
}

function NeonGlowAccent({ style }) {
  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        filter: "blur(60px)",
        pointerEvents: "none",
        zIndex: 0,
        ...style,
      }}
    />
  );
}

function MainColumn({
  p,
  files,
  filesRequireReselection,
  restoreWarning,
  hasFiles,
  drag,
  setDrag,
  addFiles,
  handleDrop,
  inputRef,
  processing,
  processed,
  progress,
  cropProgressMessage,
  cropBillingMessage,
  outputPdfBytes,
  outputArtifactName,
  cropTaskSummary,
  mergeError,
  ocrProcessing,
  ocrError,
  ocrColumnPreset,
  setOcrColumnPreset,
  ocrCustomColumns,
  setOcrCustomColumns,
  ocrMaxWorkers,
  setOcrMaxWorkers,
  ocrTaskStatus,
  ocrProgress,
  ocrProgressMessage,
  returnAnalysisProcessing,
  returnAnalysisError,
  returnAnalysisTaskStatus,
  returnAnalysisProgress,
  returnAnalysisProgressMessage,
  returnAnalysisSummary,
  returnFileName,
  setReturnFileName,
  ocrPresetOptions,
  coinGateError,
  balance,
  handleProcess,
  handleDownloadPdf,
  handleGenerateOcrExcel,
  handleStartReturnAnalysis,
  returnInputRef,
  setMergeError,
  setOcrError,
  setCoinGateError,
  setFiles,
  setProcessed,
  setProcessing,
  setProgress,
  setOutputPdfBytes,
  setOutputArtifactName,
  setOutputArtifactMime,
  setCropTaskSummary,
  setOcrTaskId,
  setOcrTaskStatus,
  setOcrProgress,
  setOcrProgressMessage,
  setReturnAnalysisTaskId,
  setReturnAnalysisTaskStatus,
  setReturnAnalysisProgress,
  setReturnAnalysisProgressMessage,
  setReturnAnalysisError,
  setReturnAnalysisSummary,
  clearActiveTask,
  sortBy,
  layoutLabel,
  cropHistory,
  historyDownloadJobId,
  handleDownloadHistoryJob,
}) {
  return (
    <div style={{ minWidth: 0 }}>
      <PreheadingPill p={p} />

      <h1
        style={{
          margin: "14px 0 12px",
          fontFamily: font,
          fontWeight: 800,
          fontSize: "clamp(26px, 3.4vw, 40px)",
          lineHeight: 1.12,
          letterSpacing: "-0.8px",
          color: brand.text,
        }}
      >
        Upload invoices,
        <br />
        get{" "}
        <span
          style={{
            color: MEESHO_NEON.pinkSoft,
            textShadow: `0 0 14px ${MEESHO_NEON.pink}44`,
          }}
        >
          print-ready
        </span>{" "}
        labels
      </h1>

      <p
        style={{
          margin: "0 0 22px",
          fontSize: 15,
          color: brand.textMuted,
          fontFamily: font,
          lineHeight: 1.6,
          maxWidth: 580,
        }}
      >
        Drop one or more <strong style={{ color: brand.text }}>{p.name} PDF</strong> invoices.
        We&apos;ll detect label areas, sort them, and build a single print-ready PDF — powered by
        the premium server cropper.
      </p>

      <div
        className="meesho-upload-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          marginBottom: 12,
        }}
      >
        <UploadCard
          p={p}
          kind="drop"
          drag={drag}
          setDrag={setDrag}
          handleDrop={handleDrop}
          inputRef={inputRef}
        />
        <UploadCard
          p={p}
          kind="browse"
          drag={drag}
          setDrag={setDrag}
          handleDrop={handleDrop}
          inputRef={returnInputRef}
        />
      </div>

      {hasFiles && !processed && (
        <QueuedFilesPanel
          p={p}
          files={files}
          setFiles={setFiles}
          inputRef={inputRef}
          processed={processed}
        />
      )}

      <PrimaryCta
        p={p}
        hasFiles={hasFiles}
        processing={processing}
        processed={processed}
        filesRequireReselection={filesRequireReselection}
        handleProcess={handleProcess}
      />

      {(returnFileName ||
        returnAnalysisProcessing ||
        returnAnalysisSummary ||
        returnAnalysisError ||
        (returnAnalysisTaskStatus && returnAnalysisTaskStatus !== "idle")) && (
        <ReturnAnalysisPanel
          fileName={returnFileName}
          processing={returnAnalysisProcessing}
          taskStatus={returnAnalysisTaskStatus}
          progress={returnAnalysisProgress}
          message={returnAnalysisProgressMessage}
          summary={returnAnalysisSummary}
          error={returnAnalysisError}
          onReupload={() => {
            if (returnInputRef?.current) returnInputRef.current.value = "";
            returnInputRef?.current?.click();
          }}
          onReset={() => {
            setReturnFileName("");
            setReturnAnalysisTaskId?.("");
            setReturnAnalysisTaskStatus?.("idle");
            setReturnAnalysisProgress?.(0);
            setReturnAnalysisProgressMessage?.("");
            setReturnAnalysisError?.(null);
            setReturnAnalysisSummary?.(null);
          }}
        />
      )}

      {processing && <ProgressPanel p={p} progress={progress} message={cropProgressMessage} />}

      {cropBillingMessage && !processing && (
        <BillingInfoPanel message={cropBillingMessage} />
      )}

      {mergeError && !processing && (
        <ErrorPanel
          title="Could not build the PDF"
          message={mergeError}
          onDismiss={() => {
            setMergeError(null);
            setCoinGateError(false);
          }}
        />
      )}

      {coinGateError && !processing && (
        <CoinGatePanel balance={balance} onDismiss={() => setCoinGateError(false)} />
      )}

      {processed && (
        <ResultPanel
          p={p}
          files={files}
          sortBy={sortBy}
          layoutLabel={layoutLabel}
          outputArtifactName={outputArtifactName}
          cropTaskSummary={cropTaskSummary}
          handleDownloadPdf={handleDownloadPdf}
        />
      )}

      {Array.isArray(cropHistory) && cropHistory.length > 0 ? (
        <CropHistoryGrid
          p={p}
          entries={cropHistory}
          downloadingJobId={historyDownloadJobId}
          onDownloadJob={handleDownloadHistoryJob}
        />
      ) : null}

    </div>
  );
}

function CropHistoryGrid({ p, entries, downloadingJobId, onDownloadJob }) {
  const recent = Array.isArray(entries) ? entries : [];
  const historyViewportHeight = 332; // ~5 rows visible, older rows scroll
  return (
    <div
      style={{
        marginTop: 12,
        marginBottom: 8,
        borderRadius: 14,
        border: `1px solid ${MEESHO_NEON.cardBorder}`,
        background: "rgba(20, 22, 30, 0.6)",
        padding: "12px 12px 10px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 10,
          marginBottom: 10,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontFamily: font, fontSize: 13, fontWeight: 800, color: brand.text }}>
          Recent crop jobs
        </span>
        <span style={{ fontFamily: font, fontSize: 11.5, color: brand.textDim }}>
          {recent.length} total
        </span>
      </div>
      <div
        style={{
          fontFamily: font,
          fontSize: 11.5,
          color: brand.textDim,
          marginBottom: 10,
        }}
      >
        Recent jobs stay visible across days; download files are auto-cleaned daily.
      </div>

      {recent.length ? (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 8,
            maxHeight: historyViewportHeight,
            overflowY: recent.length > 5 ? "auto" : "visible",
            paddingRight: recent.length > 5 ? 4 : 0,
          }}
        >
          {recent.map((it, idx) => {
            const sortLabel =
              SORT_OPTIONS.find((s) => s.value === it.sort_by)?.label || it.sort_by || "-";
            const outLayoutLabel =
              OUTPUT_LAYOUTS.find((l) => l.value === it.layout)?.label || it.layout || "-";
            const effectiveStatus =
              String(it?.task_status || "").toLowerCase() === "success"
                ? "success"
                : String(it?.status || "").toLowerCase();
            const expired = effectiveStatus === "success" && it.download_available === false;
            const downloadDisabled =
              !it.task_id || expired || String(downloadingJobId || "") === String(it.id || "");
            return (
              <div
                key={it.id ?? idx}
                style={{
                  borderRadius: 10,
                  border: `1px solid ${MEESHO_NEON.cardBorder}`,
                  background: "rgba(11, 18, 32, 0.62)",
                  padding: "8px 10px",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 10,
                  flexWrap: "wrap",
                }}
              >
                <div
                  style={{ fontFamily: font, fontSize: 12.5, fontWeight: 700, color: brand.text }}
                >
                  {idx + 1}. Job #{it.id ?? "N/A"} · {it.total_input_files || 0} file
                  {(it.total_input_files || 0) === 1 ? "" : "s"}
                </div>
                <div
                  style={{
                    fontFamily: font,
                    fontSize: 11.5,
                    color: brand.textMuted,
                    lineHeight: 1.35,
                    flex: 1,
                  }}
                >
                  Status: {effectiveStatus || "unknown"} · Sort: {sortLabel} · {outLayoutLabel} · Labels:{" "}
                  {it.total_output_labels || 0} · Pages: {it.total_input_pages || 0} ·{" "}
                  {(it.duration_ms || 0) > 0 ? `${it.duration_ms}ms` : "duration -"}
                </div>
                <div style={{ fontFamily: font, fontSize: 11, color: brand.textDim }}>
                  {it.created_at
                    ? new Date(it.created_at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : "--:--"}
                </div>
                {effectiveStatus === "success" ? (
                  <button
                    type="button"
                    disabled={downloadDisabled}
                    onClick={() => onDownloadJob?.(it)}
                    style={{
                      padding: "6px 10px",
                      borderRadius: 8,
                      border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
                      background: accent(0.12),
                      color: brand.text,
                      fontFamily: font,
                      fontSize: 11.5,
                      fontWeight: 700,
                      cursor: downloadDisabled ? "not-allowed" : "pointer",
                      opacity: downloadDisabled ? 0.6 : 1,
                    }}
                  >
                    {String(downloadingJobId || "") === String(it.id || "")
                      ? "Downloading..."
                      : expired
                        ? "Expired"
                        : "Download"}
                  </button>
                ) : null}
                {effectiveStatus === "failed" && it.error_message ? (
                  <div style={{ width: "100%", fontFamily: font, fontSize: 11, color: "#fca5a5" }}>
                    Error: {it.error_message}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div style={{ fontFamily: font, fontSize: 12, color: brand.textDim }}>
          No crop jobs found for {p.name}.
        </div>
      )}
    </div>
  );
}

function PreheadingPill({ p }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 12px",
        borderRadius: 999,
        background: accent(0.1),
        border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
        boxShadow: `inset 0 0 12px ${accent(0.12)}`,
        fontSize: 11,
        fontWeight: 800,
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        color: MEESHO_NEON.pinkSoft,
        fontFamily: font,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: MEESHO_NEON.pink,
          boxShadow: `0 0 10px ${MEESHO_NEON.pink}`,
        }}
      />
      {p.name} • Label cropper
    </span>
  );
}

function UploadCard({ p, kind, drag, setDrag, handleDrop, inputRef }) {
  const isDrop = kind === "drop";
  const title = isDrop ? "Upload Label PDFs" : "Upload return excel";
  const helper = isDrop
    ? `Drop one or more ${p.name} invoice PDFs right here.`
    : "Pick return excel from your computer.";
  const buttonLabel = isDrop ? "Choose PDF files" : "Choose excel file";

  const onClick = () => {
    if (inputRef.current) inputRef.current.value = "";
    inputRef.current?.click();
  };

  return (
    <div
      onDragOver={
        isDrop
          ? (e) => {
              e.preventDefault();
              setDrag(true);
            }
          : undefined
      }
      onDragLeave={isDrop ? () => setDrag(false) : undefined}
      onDrop={isDrop ? handleDrop : undefined}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
      style={{
        cursor: "pointer",
        position: "relative",
        borderRadius: 14,
        border: `2px dashed ${isDrop && drag ? MEESHO_NEON.pink : MEESHO_NEON.cardBorderStrong}`,
        background: isDrop && drag ? accent(0.08) : "rgba(20, 22, 30, 0.55)",
        padding: "14px 14px 12px",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        textAlign: "center",
        gap: 6,
        minHeight: 156,
        boxShadow:
          isDrop && drag
            ? `0 0 0 4px ${accent(0.18)}, 0 14px 38px ${accent(0.18)}`
            : "0 8px 28px rgba(0,0,0,0.25)",
        transition: "border-color 0.18s, background 0.18s, box-shadow 0.18s, transform 0.18s",
      }}
    >
      <div
        style={{
          width: 40,
          height: 40,
          borderRadius: 12,
          background: `linear-gradient(145deg, ${accent(0.22)} 0%, rgba(99, 102, 241, 0.18) 100%)`,
          border: `1px solid ${accent(0.35)}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 4,
          boxShadow: `inset 0 0 14px ${accent(0.18)}`,
        }}
      >
        {isDrop ? (
          <UploadIcon color={MEESHO_NEON.pinkSoft} size={22} />
        ) : (
          <FolderIcon color={MEESHO_NEON.pinkSoft} size={22} />
        )}
      </div>
      <div
        style={{
          fontFamily: font,
          fontWeight: 800,
          fontSize: 13.5,
          color: brand.text,
          letterSpacing: "-0.2px",
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontFamily: font,
          fontSize: 11.5,
          color: brand.textMuted,
          maxWidth: 200,
          lineHeight: 1.45,
        }}
      >
        {helper}
      </div>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          if (inputRef.current) inputRef.current.value = "";
          inputRef.current?.click();
        }}
        style={{
          marginTop: 4,
          padding: "7px 14px",
          borderRadius: 10,
          background: MEESHO_NEON.ctaGradient,
          color: "#fff",
          border: "1px solid rgba(255,255,255,0.18)",
          cursor: "pointer",
          fontSize: 12,
          fontWeight: 800,
          fontFamily: font,
          letterSpacing: "-0.1px",
          boxShadow: MEESHO_NEON.ctaGlow,
        }}
      >
        {buttonLabel}
      </button>
      <div
        style={{
          marginTop: "auto",
          fontFamily: font,
          fontSize: 10,
          color: brand.textDim,
          paddingTop: 8,
        }}
      >
        {isDrop ? "Max ~50 MB per file · PDF only" : "Excel only (.xlsx / .xls)"}
      </div>
    </div>
  );
}

function FolderIcon({ size = 24, color = "#fff" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
      <path d="M3 11h18" />
    </svg>
  );
}

function QueuedFilesPanel({ p, files, setFiles, inputRef, processed }) {
  return (
    <div
      style={{
        marginBottom: 16,
        borderRadius: 18,
        border: `1.5px solid ${MEESHO_NEON.cardBorderStrong}`,
        background: MEESHO_NEON.cardBg,
        padding: "18px 18px 16px",
        boxShadow: "0 8px 28px rgba(0,0,0,0.25)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 12,
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <div>
          <p
            style={{
              margin: 0,
              fontSize: 11,
              fontWeight: 800,
              color: MEESHO_NEON.pinkSoft,
              fontFamily: font,
              textTransform: "uppercase",
              letterSpacing: "0.1em",
            }}
          >
            Queued files
          </p>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 17,
              fontWeight: 800,
              color: brand.text,
              fontFamily: font,
            }}
          >
            {files.length} PDF{files.length !== 1 ? "s" : ""} ready
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            if (inputRef.current) inputRef.current.value = "";
            inputRef.current?.click();
          }}
          style={{
            fontSize: 13,
            padding: "8px 14px",
            border: `1.5px solid ${MEESHO_NEON.pinkSoft}`,
            color: MEESHO_NEON.pinkSoft,
            background: accent(0.08),
            borderRadius: 10,
            cursor: "pointer",
            fontFamily: font,
            fontWeight: 700,
          }}
        >
          + Add more PDFs
        </button>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {files.map((f, i) => (
          <FileItem
            key={`${f.name}-${i}`}
            file={f}
            platform={p}
            processed={processed}
            onRemove={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
          />
        ))}
      </div>
    </div>
  );
}

function PrimaryCta({ p, hasFiles, processing, processed, filesRequireReselection, handleProcess }) {
  const enabled = hasFiles && !processing && !processed;
  return (
    <button
      type="button"
      onClick={handleProcess}
      disabled={!enabled}
      style={{
        width: "100%",
        padding: "10px 14px",
        borderRadius: 12,
        border: "1px solid rgba(255,255,255,0.16)",
        background: enabled ? MEESHO_NEON.ctaGradient : "rgba(148, 163, 184, 0.18)",
        color: "#fff",
        cursor: enabled ? "pointer" : "not-allowed",
        fontFamily: font,
        fontWeight: 800,
        fontSize: 14,
        letterSpacing: "-0.2px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        boxShadow: enabled ? MEESHO_NEON.ctaGlow : "none",
        animation: enabled ? "meeshoNeonPulse 2.6s ease-in-out infinite" : "none",
        opacity: processing || processed ? 0.85 : 1,
        transition: "background 0.18s, box-shadow 0.18s, transform 0.12s",
      }}
    >
      {processing ? (
        <>
          <div
            style={{
              width: 18,
              height: 18,
              borderRadius: "50%",
              border: "2px solid rgba(255,255,255,0.35)",
              borderTopColor: "#fff",
              animation: "spin 0.7s linear infinite",
            }}
          />
          Zero Ai Agent Cropping &amp; Sorting...
        </>
      ) : processed ? (
        <>✓ Finished — see download below</>
      ) : filesRequireReselection ? (
        <>Reselect PDFs first</>
      ) : (
        <>
          <BoltIcon /> Crop labels now
        </>
      )}
    </button>
  );
}

function SecondaryOcrCta({ ocrTaskStatus, ocrProgress, ocrProgressMessage }) {
  return (
    <div
      style={{
        marginTop: 10,
        padding: "10px 12px",
        borderRadius: 12,
        border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
        background: "rgba(11, 18, 32, 0.62)",
      }}
    >
      <div style={{ fontFamily: font, fontSize: 12, color: brand.textMuted, lineHeight: 1.45 }}>
        OCR data collection runs automatically in backend when you crop labels.
      </div>
      {ocrTaskStatus && ocrTaskStatus !== "idle" ? (
        <div style={{ marginTop: 6, fontFamily: font, fontSize: 11.5, color: brand.textDim }}>
          Background OCR: {ocrTaskStatus} ·{" "}
          {Math.max(0, Math.min(100, Math.round(ocrProgress || 0)))}%
          {ocrProgressMessage ? ` · ${ocrProgressMessage}` : ""}
        </div>
      ) : null}
    </div>
  );
}

function BoltIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M13 2L4 14h7l-1 8 10-12h-7l1-8z"
        fill="#fff"
        stroke="rgba(255,255,255,0.65)"
        strokeWidth="1"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ProgressPanel({ p, progress, message }) {
  return (
    <div
      style={{
        marginTop: 16,
        background: "rgba(20, 22, 30, 0.85)",
        border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
        borderRadius: 16,
        padding: "18px 20px",
        boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <span style={{ fontFamily: font, fontWeight: 700, fontSize: 14, color: brand.text }}>
          Zero Ai Agent Cropping &amp; Sorting...
        </span>
        <span
          style={{
            fontSize: 14,
            fontWeight: 800,
            color: MEESHO_NEON.pinkSoft,
            fontFamily: font,
          }}
        >
          {Math.min(Math.round(progress), 100)}%
        </span>
      </div>
      <div
        style={{
          height: 8,
          borderRadius: 999,
          background: "rgba(255,255,255,0.06)",
          overflow: "hidden",
          border: "1px solid rgba(255,255,255,0.05)",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${Math.min(progress, 100)}%`,
            background: MEESHO_NEON.ctaGradient,
            borderRadius: 999,
            transition: "width 0.16s ease",
            boxShadow: MEESHO_NEON.ctaGlow,
          }}
        />
      </div>
      <p
        style={{
          margin: "10px 0 0",
          fontSize: 12,
          color: brand.textMuted,
          fontFamily: font,
          lineHeight: 1.45,
        }}
      >
        {(message || "").trim() || "Reading pages · finding label edges · applying your sort order"}
      </p>
    </div>
  );
}

function ReturnAnalysisPanel({
  fileName,
  processing,
  taskStatus,
  progress,
  message,
  summary,
  error,
  onReupload,
  onReset,
}) {
  const status = String(taskStatus || "idle").toLowerCase();
  const isFailed =
    Boolean(error) || status === "failed" || status === "cancelled" || status === "expired";
  const isDone = !isFailed && (status === "success" || Boolean(summary));
  const isQueued = !isDone && !isFailed && status === "queued";
  const isRunning = !isDone && !isFailed && (processing || status === "running");
  const showProgressBar = isQueued || isRunning;
  const pct = Math.max(0, Math.min(100, Math.round(progress || 0)));

  const statusLabel = isFailed
    ? "Failed"
    : isDone
      ? "Completed"
      : isQueued
        ? "Queued"
        : isRunning
          ? "Processing"
          : "Uploaded";
  const statusColor = isFailed ? "#fca5a5" : isDone ? "#86efac" : MEESHO_NEON.pinkSoft;
  const statusBg = isFailed
    ? "rgba(127, 29, 29, 0.35)"
    : isDone
      ? "rgba(22, 101, 52, 0.32)"
      : accent(0.14);
  const statusBorder = isFailed
    ? "rgba(248, 113, 113, 0.45)"
    : isDone
      ? "rgba(74, 222, 128, 0.45)"
      : MEESHO_NEON.cardBorderStrong;

  const hint = isFailed
    ? "Could not analyse this Excel."
    : isDone
      ? "Analysis stored securely on the server."
      : isQueued
        ? "File received · waiting for a worker"
        : isRunning
          ? "Crunching rows on the server"
          : "File uploaded";

  return (
    <div
      style={{
        marginTop: 16,
        background: "rgba(20, 22, 30, 0.85)",
        border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
        borderRadius: 16,
        padding: "16px 18px 14px",
        boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginBottom: 10,
        }}
      >
        <div
          style={{
            position: "relative",
            width: 38,
            height: 38,
            flexShrink: 0,
            borderRadius: 10,
            background: `linear-gradient(145deg, ${accent(0.22)} 0%, rgba(99, 102, 241, 0.18) 100%)`,
            border: `1px solid ${accent(0.35)}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: `inset 0 0 12px ${accent(0.18)}`,
          }}
        >
          <SpreadsheetIcon color={MEESHO_NEON.pinkSoft} size={20} />
          {(isQueued || isRunning) && (
            <span
              aria-hidden
              style={{
                position: "absolute",
                inset: -3,
                borderRadius: 12,
                border: `2px solid ${accent(0.35)}`,
                borderTopColor: MEESHO_NEON.pink,
                animation: "spin 1.05s linear infinite",
                pointerEvents: "none",
              }}
            />
          )}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontFamily: font,
              fontWeight: 800,
              fontSize: 14.5,
              color: brand.text,
              letterSpacing: "-0.2px",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
            title={fileName || "Return Excel"}
          >
            {fileName || "Return Excel"}
          </div>
          <div
            style={{
              marginTop: 2,
              fontFamily: font,
              fontSize: 11.5,
              color: brand.textMuted,
              lineHeight: 1.4,
            }}
          >
            {hint}
          </div>
        </div>
        <span
          style={{
            flexShrink: 0,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 10px",
            borderRadius: 999,
            background: statusBg,
            border: `1px solid ${statusBorder}`,
            color: statusColor,
            fontFamily: font,
            fontSize: 11.5,
            fontWeight: 800,
            letterSpacing: "0.04em",
            textTransform: "uppercase",
          }}
        >
          {(isQueued || isRunning) && (
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: MEESHO_NEON.pink,
                boxShadow: `0 0 8px ${MEESHO_NEON.pink}`,
                animation: "meeshoNeonPulse 1.4s ease-in-out infinite",
              }}
            />
          )}
          {statusLabel}
          {showProgressBar ? ` · ${pct}%` : null}
        </span>
      </div>

      {showProgressBar && (
        <>
          <div
            style={{
              height: 8,
              borderRadius: 999,
              background: "rgba(255,255,255,0.06)",
              overflow: "hidden",
              border: "1px solid rgba(255,255,255,0.05)",
            }}
          >
            <div
              style={{
                height: "100%",
                width: `${pct}%`,
                background: MEESHO_NEON.ctaGradient,
                borderRadius: 999,
                transition: "width 0.18s ease",
                boxShadow: MEESHO_NEON.ctaGlow,
              }}
            />
          </div>
          <p
            style={{
              margin: "8px 0 0",
              fontSize: 12,
              color: brand.textMuted,
              fontFamily: font,
              lineHeight: 1.45,
            }}
          >
            {String(message || "").trim() ||
              "Reading sheets · matching suborders · scoring returns"}
          </p>
        </>
      )}

      {isDone && summary ? (
        <div
          style={{
            marginTop: 10,
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
            gap: 8,
          }}
        >
          <SummaryStat label="Order rows" value={summary.total_order_rows ?? "-"} />
          <SummaryStat label="Returns" value={summary.total_returns ?? "-"} />
          <SummaryStat label="Matched" value={summary.matched_returns ?? "-"} tone="ok" />
          <SummaryStat
            label="Unmatched"
            value={summary.unmatched_returns ?? "-"}
            tone={Number(summary.unmatched_returns || 0) > 0 ? "warn" : undefined}
          />
          <SummaryStat
            label="Match rate"
            value={
              Number.isFinite(Number(summary.match_rate_pct))
                ? `${Number(summary.match_rate_pct).toFixed(1)}%`
                : "-"
            }
            tone="ok"
          />
        </div>
      ) : null}

      {isFailed ? (
        <div
          style={{
            marginTop: 10,
            padding: "10px 12px",
            borderRadius: 12,
            border: "1px solid rgba(248, 113, 113, 0.35)",
            background: "rgba(127, 29, 29, 0.25)",
            fontFamily: font,
            fontSize: 12.5,
            color: "#fca5a5",
            lineHeight: 1.45,
          }}
        >
          {String(error || message || "Return analysis task failed.")}
        </div>
      ) : null}

      <div
        style={{
          marginTop: 12,
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          justifyContent: "flex-end",
        }}
      >
        {!processing && (isDone || isFailed) ? (
          <button
            type="button"
            onClick={onReupload}
            style={{
              padding: "8px 14px",
              borderRadius: 10,
              background: MEESHO_NEON.ctaGradient,
              color: "#fff",
              border: "1px solid rgba(255,255,255,0.18)",
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 800,
              fontFamily: font,
              boxShadow: MEESHO_NEON.ctaGlow,
            }}
          >
            Upload another Excel
          </button>
        ) : null}
        {!processing && (isDone || isFailed) ? (
          <button
            type="button"
            onClick={onReset}
            style={{
              padding: "8px 14px",
              borderRadius: 10,
              background: "rgba(255,255,255,0.06)",
              color: brand.textMuted,
              border: `1px solid ${MEESHO_NEON.cardBorder}`,
              cursor: "pointer",
              fontSize: 12,
              fontWeight: 700,
              fontFamily: font,
            }}
          >
            Dismiss
          </button>
        ) : null}
      </div>
    </div>
  );
}

function SummaryStat({ label, value, tone }) {
  const toneColor = tone === "ok" ? "#86efac" : tone === "warn" ? "#fcd34d" : MEESHO_NEON.pinkSoft;
  return (
    <div
      style={{
        padding: "8px 10px",
        borderRadius: 10,
        border: `1px solid ${MEESHO_NEON.cardBorder}`,
        background: "rgba(11, 18, 32, 0.62)",
      }}
    >
      <div
        style={{
          fontFamily: font,
          fontSize: 10.5,
          fontWeight: 700,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: brand.textDim,
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: font,
          fontSize: 16,
          fontWeight: 800,
          color: toneColor,
          letterSpacing: "-0.3px",
        }}
      >
        {value}
      </div>
    </div>
  );
}

function SpreadsheetIcon({ size = 20, color = "#fff" }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      stroke={color}
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="3" y="3" width="18" height="18" rx="2.5" />
      <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  );
}

function ErrorPanel({ title, message, onDismiss }) {
  return (
    <div
      style={{
        marginTop: 16,
        background: "rgba(127, 29, 29, 0.25)",
        border: "1px solid rgba(248, 113, 113, 0.35)",
        borderRadius: 16,
        padding: "18px 20px",
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: 15,
          fontWeight: 800,
          color: "#fecaca",
          fontFamily: font,
          marginBottom: 6,
        }}
      >
        {title}
      </p>
      <p
        style={{
          margin: "0 0 14px",
          fontSize: 13,
          color: "#fca5a5",
          fontFamily: font,
          lineHeight: 1.5,
        }}
      >
        {message}
      </p>
      <button
        type="button"
        onClick={onDismiss}
        style={{
          padding: "8px 16px",
          borderRadius: 10,
          background: "rgba(255,255,255,0.08)",
          border: "1px solid rgba(248, 113, 113, 0.45)",
          cursor: "pointer",
          fontFamily: font,
          fontWeight: 600,
          fontSize: 13,
          color: "#fecaca",
        }}
      >
        Dismiss
      </button>
    </div>
  );
}

function BillingInfoPanel({ message }) {
  return (
    <div
      style={{
        marginTop: 12,
        borderRadius: 14,
        border: `1px solid ${MEESHO_NEON.cardBorder}`,
        background: "rgba(30, 64, 175, 0.12)",
        padding: "12px 14px",
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: 13,
          lineHeight: 1.5,
          fontWeight: 700,
          color: "#bfdbfe",
          fontFamily: MEESHO_NEON.font,
        }}
      >
        {message}
      </p>
    </div>
  );
}

function CoinGatePanel({ balance, onDismiss }) {
  return (
    <div
      style={{
        marginTop: 16,
        background: "rgba(120, 53, 15, 0.35)",
        border: "1px solid rgba(253, 224, 71, 0.35)",
        borderRadius: 16,
        padding: "18px 20px",
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: 15,
          fontWeight: 800,
          color: "#fde68a",
          fontFamily: font,
          marginBottom: 6,
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        <CoinIcon size={20} alt="" />
        Not enough coins
      </p>
      <p
        style={{
          margin: "0 0 14px",
          fontSize: 13,
          color: "#fcd34d",
          fontFamily: font,
          lineHeight: 1.5,
        }}
      >
        Premium crop billing is{" "}
        <strong>{PREMIUM_CROP_COIN_COST_PER_LABEL} coin per label</strong> when any premium
        feature is enabled. You have <strong>{balance}</strong>. Contact admin to add coins.
      </p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        <Link
          to="/wallet"
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "10px 18px",
            borderRadius: 10,
            background: "#D97706",
            color: "#fff",
            fontWeight: 700,
            fontSize: 13,
            fontFamily: font,
            textDecoration: "none",
          }}
        >
          Go to wallet
        </Link>
        <button
          type="button"
          onClick={onDismiss}
          style={{
            padding: "10px 16px",
            borderRadius: 10,
            background: "rgba(255,255,255,0.08)",
            border: "1px solid rgba(253, 224, 71, 0.4)",
            cursor: "pointer",
            fontFamily: font,
            fontWeight: 600,
            fontSize: 13,
            color: "#fef3c7",
          }}
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

function ResultCourierBreakdown({ summary, platformId }) {
  if (!summary || typeof summary !== "object") return null;
  const raw = summary.courier_counts;
  if (!raw || typeof raw !== "object") return null;
  const entries = Object.entries(raw)
    .map(([name, value]) => [normalizeCourierName(name), Number(value) || 0])
    .filter(([, value]) => value > 0);
  if (!entries.length) return null;
  sortCourierEntries(entries);
  const total =
    Number(summary.courier_count_total) || entries.reduce((acc, [, value]) => acc + value, 0);
  const error = String(summary.courier_count_error || "");
  const isFlipkart = platformId === "flipkart";
  const heading = isFlipkart ? "Total orders per seller" : "Total orders per courier partner";
  const helperText = isFlipkart
    ? "Flipkart labels are grouped by Sold By when available, with courier-partner fallback when seller details are missing."
    : "Use these counts to verify with the delivery personnel before handing over the parcels.";
  return (
    <div
      style={{
        marginBottom: 14,
        padding: "12px 14px",
        borderRadius: 12,
        background: "rgba(15, 23, 42, 0.45)",
        border: "1px solid rgba(74, 222, 128, 0.25)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 6,
        }}
      >
        <span style={{ fontFamily: font, fontSize: 13.5, fontWeight: 700, color: "#bbf7d0" }}>
          {heading}
        </span>
        <span style={{ fontFamily: font, fontSize: 12, color: "#86efac" }}>
          {total} label{total === 1 ? "" : "s"} counted
        </span>
      </div>
      <p
        style={{
          fontFamily: font,
          fontSize: 12,
          color: "#cbd5f5",
          marginBottom: 8,
          lineHeight: 1.5,
        }}
      >
        {helperText}
      </p>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "grid",
          gap: 6,
        }}
      >
        {entries.map(([name, value]) => (
          <li
            key={name}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              padding: "5px 10px",
              borderRadius: 8,
              background: "rgba(15, 118, 110, 0.18)",
              border: "1px solid rgba(74, 222, 128, 0.18)",
            }}
          >
            <span
              style={{
                fontFamily: font,
                fontSize: 13,
                fontWeight: 600,
                color: name === "Unknown" ? "#fbbf24" : "#e0f2fe",
              }}
            >
              {name}
            </span>
            <span style={{ fontFamily: font, fontSize: 13, fontWeight: 700, color: "#bbf7d0" }}>
              {value}
            </span>
          </li>
        ))}
      </ul>
      {error ? (
        <p style={{ marginTop: 6, fontFamily: font, fontSize: 11, color: "#fca5a5" }}>
          Some pages could not be parsed: {error}
        </p>
      ) : null}
    </div>
  );
}

function SortBoxCourierBreakdown({ summary, platformId, onReset }) {
  if (!summary || typeof summary !== "object") return null;
  const raw = summary.courier_counts;
  if (!raw || typeof raw !== "object") return null;
  const entries = Object.entries(raw)
    .map(([name, value]) => [normalizeCourierName(name), Number(value) || 0])
    .filter(([, value]) => value > 0);
  if (!entries.length) return null;
  sortCourierEntries(entries);
  const total =
    Number(summary.courier_count_total) || entries.reduce((acc, [, value]) => acc + value, 0);
  const hasReset = typeof onReset === "function";
  const isFlipkart = platformId === "flipkart";
  const heading = isFlipkart ? "Seller Total Count" : "Courier Total Count";
  return (
    <div
      style={{
        marginTop: 10,
        paddingTop: 10,
        borderTop: "1px solid rgba(148, 163, 184, 0.2)",
        display: "grid",
        gap: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          padding: "2px 9px 0",
        }}
      >
        <span
          style={{
            fontFamily: font,
            fontSize: 11.5,
            fontWeight: 700,
            color: "#86efac",
            letterSpacing: "0.03em",
            textTransform: "uppercase",
          }}
        >
          {heading}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              fontFamily: font,
              fontSize: 17,
              fontWeight: 700,
              color: "#bbf7d0",
              minWidth: 36,
              textAlign: "right",
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {total}
          </span>
          {hasReset ? (
            <button
              type="button"
              onClick={onReset}
              style={{
                border: "1px solid rgba(134, 239, 172, 0.45)",
                background: "rgba(15, 23, 42, 0.65)",
                color: "#bbf7d0",
                borderRadius: 8,
                padding: "3px 8px",
                fontSize: 11,
                fontWeight: 700,
                fontFamily: font,
                cursor: "pointer",
              }}
            >
              Reset
            </button>
          ) : null}
        </div>
      </div>
      {entries.map(([name, value]) => (
        <div
          key={`sort-courier-${name}`}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
            padding: "6px 9px",
            borderRadius: 8,
            border: "1px solid rgba(74, 222, 128, 0.18)",
            background: "rgba(15, 118, 110, 0.14)",
          }}
        >
          <span
            style={{
              fontFamily: font,
              fontSize: 12.5,
              fontWeight: 600,
              color: name === "Unknown" ? "#fbbf24" : "#e0f2fe",
            }}
          >
            {name}
          </span>
          <span style={{ fontFamily: font, fontSize: 12.5, fontWeight: 700, color: "#bbf7d0" }}>
            {value}
          </span>
        </div>
      ))}
    </div>
  );
}

function ResultPanel({
  p,
  files,
  sortBy,
  layoutLabel,
  outputArtifactName,
  cropTaskSummary,
  handleDownloadPdf,
}) {
  return (
    <div
      style={{
        marginTop: 16,
        background: "rgba(22, 101, 52, 0.30)",
        border: "1px solid rgba(74, 222, 128, 0.35)",
        borderRadius: 16,
        padding: "18px 20px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 10 }}>
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            background: "#16A34A",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <CheckIcon size={14} />
        </div>
        <span style={{ fontFamily: font, fontWeight: 800, fontSize: 17, color: "#bbf7d0" }}>
          {files.length > 1 ? "Merged PDF ready" : "PDF ready"}
        </span>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={handleDownloadPdf}
          style={{
            padding: "10px 20px",
            borderRadius: 11,
            background: "#16A34A",
            color: "#fff",
            border: "none",
            cursor: "pointer",
            fontSize: 14,
            fontWeight: 700,
            fontFamily: font,
          }}
        >
          {String(outputArtifactName || "")
            .toLowerCase()
            .endsWith(".zip")
            ? "⬇ Download result ZIP"
            : "⬇ Download PDF"}
        </button>
      </div>
    </div>
  );
}

function Sidebar({
  p,
  outputLayout,
  setOutputLayout,
  sortBy,
  setSortBy,
  printDateTimeOnLabel,
  setPrintDateTimeOnLabel,
  multiOrderAtBottom,
  setMultiOrderAtBottom,
  separatePincodesEnabled,
  setSeparatePincodesEnabled,
  separatePincodes,
  setSeparatePincodes,
  detectSuspiciousBuyerEnabled,
  setDetectSuspiciousBuyerEnabled,
  suspiciousMarkerPreviewEnabled,
  setSuspiciousMarkerPreviewEnabled,
  separateMultiOrderEnabled,
  setSeparateMultiOrderEnabled,
  loyalCustomerEnabled,
  setLoyalCustomerEnabled,
  loyalCustomerPreviewEnabled,
  setLoyalCustomerPreviewEnabled,
  userHistorySuborderId,
  setUserHistorySuborderId,
  balance,
  cropTaskSummary,
  onResetCourierTotals,
}) {
  const [courierResetNotice, setCourierResetNotice] = useState(false);
  const pincodeInputRef = useRef(null);
  const pincodeOverlayRef = useRef(null);
  const pincodeValidation = useMemo(
    () => validatePincodeInput(separatePincodes),
    [separatePincodes],
  );
  const pincodeSegments = useMemo(
    () => buildPincodeHighlightSegments(separatePincodes),
    [separatePincodes],
  );
  const isFlipkart = p.id === "flipkart";
  const visibleSortOptions = isFlipkart
    ? SORT_OPTIONS.filter((opt) => opt.value === "order_id" || opt.value === "sku")
    : SORT_OPTIONS;

  useEffect(() => {
    if (isFlipkart && sortBy !== "sku" && sortBy !== "order_id") {
      setSortBy("sku");
    }
  }, [isFlipkart, sortBy, setSortBy]);

  useEffect(() => {
    if (!courierResetNotice) return undefined;
    const timer = setTimeout(() => setCourierResetNotice(false), 1800);
    return () => clearTimeout(timer);
  }, [courierResetNotice]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
      <div
        className="meesho-sidebar-row"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, alignItems: "stretch" }}
      >
        <SidebarCard title="Sort by" subtitle="Choose print format and sorting." minHeight={258}>
          <div
            style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}
          >
            {OUTPUT_LAYOUTS.map((opt) => {
              const active = outputLayout === opt.value;
              return (
                <label
                  key={opt.value}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 8,
                    textAlign: "left",
                    padding: "9px 10px",
                    borderRadius: 12,
                    border: active
                      ? `2px solid ${MEESHO_NEON.pink}`
                      : `1.5px solid ${MEESHO_NEON.cardBorder}`,
                    background: active ? accent(0.1) : "rgba(255,255,255,0.04)",
                    cursor: "pointer",
                    transition: "border-color 0.15s, background 0.15s, transform 0.15s",
                    fontFamily: font,
                    minHeight: 76,
                  }}
                >
                  <input
                    type="radio"
                    name="outputLayoutNeon"
                    value={opt.value}
                    checked={active}
                    onChange={(e) => setOutputLayout(e.target.value)}
                    style={{ accentColor: MEESHO_NEON.pink, marginTop: 2, width: 14, height: 14 }}
                  />
                  <span style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
                    <span style={{ fontSize: 16, lineHeight: 1 }}>{opt.icon}</span>
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 800,
                        color: brand.text,
                        letterSpacing: "-0.2px",
                      }}
                    >
                      {opt.label}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {visibleSortOptions.map((opt) => {
              const active = sortBy === opt.value;
              const sortLabel =
                opt.value === "order_id"
                  ? "Sold by"
                  : opt.value === "delivery"
                    ? "Courier Partners"
                    : opt.label;
              return (
                <label
                  key={opt.value}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "10px 12px",
                    cursor: "pointer",
                    border: active
                      ? `1.5px solid ${MEESHO_NEON.pink}`
                      : `1.5px solid ${MEESHO_NEON.cardBorder}`,
                    borderRadius: 12,
                    background: active ? accent(0.1) : "rgba(255,255,255,0.04)",
                    transition: "all 0.15s",
                  }}
                >
                  <input
                    type="checkbox"
                    value={opt.value}
                    checked={active}
                    onChange={(e) => setSortBy(e.target.value)}
                    style={{
                      accentColor: MEESHO_NEON.pink,
                      width: 15,
                      height: 15,
                      flexShrink: 0,
                      cursor: "pointer",
                    }}
                  />
                  <span
                    style={{
                      fontSize: 13,
                      fontFamily: font,
                      color: active ? brand.text : brand.textMuted,
                      fontWeight: active ? 700 : 500,
                      flex: 1,
                    }}
                  >
                    {sortLabel}
                  </span>
                </label>
              );
            })}
            {!isFlipkart && (
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 12px",
                  cursor: "pointer",
                  border: printDateTimeOnLabel
                    ? `1.5px solid ${MEESHO_NEON.pink}`
                    : `1.5px solid ${MEESHO_NEON.cardBorder}`,
                  borderRadius: 12,
                  background: printDateTimeOnLabel ? accent(0.1) : "rgba(255,255,255,0.04)",
                  transition: "all 0.15s",
                }}
              >
                <input
                  type="checkbox"
                  checked={printDateTimeOnLabel}
                  onChange={(e) => setPrintDateTimeOnLabel(e.target.checked)}
                  style={{
                    accentColor: MEESHO_NEON.pink,
                    width: 15,
                    height: 15,
                    flexShrink: 0,
                    cursor: "pointer",
                  }}
                />
                <span
                  style={{
                    fontSize: 13,
                    fontFamily: font,
                    color: printDateTimeOnLabel ? brand.text : brand.textMuted,
                    fontWeight: printDateTimeOnLabel ? 700 : 500,
                    flex: 1,
                  }}
                >
                  Print Date &amp; Time on Label
                </span>
              </label>
            )}
            <label
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "10px 12px",
                cursor: "pointer",
                border: multiOrderAtBottom
                  ? `1.5px solid ${MEESHO_NEON.pink}`
                  : `1.5px solid ${MEESHO_NEON.cardBorder}`,
                borderRadius: 12,
                background: multiOrderAtBottom ? accent(0.1) : "rgba(255,255,255,0.04)",
                transition: "all 0.15s",
              }}
            >
              <input
                type="checkbox"
                checked={multiOrderAtBottom}
                onChange={(e) => setMultiOrderAtBottom(e.target.checked)}
                style={{
                  accentColor: MEESHO_NEON.pink,
                  width: 15,
                  height: 15,
                  flexShrink: 0,
                  cursor: "pointer",
                }}
              />
              <span
                style={{
                  fontSize: 13,
                  fontFamily: font,
                  color: multiOrderAtBottom ? brand.text : brand.textMuted,
                  fontWeight: multiOrderAtBottom ? 700 : 500,
                  flex: 1,
                }}
              >
                Multi Quantity Orders at Last
              </span>
            </label>
            <SortBoxCourierBreakdown
              summary={cropTaskSummary}
              platformId={p.id}
              onReset={() => {
                onResetCourierTotals?.();
                setCourierResetNotice(true);
              }}
            />
            {courierResetNotice ? (
              <p
                style={{
                  margin: "6px 8px 0",
                  fontFamily: font,
                  fontSize: 11.5,
                  color: "#86efac",
                  lineHeight: 1.35,
                }}
              >
                {isFlipkart ? "Seller totals reset." : "Courier totals reset."}
              </p>
            ) : null}
          </div>
        </SidebarCard>

        <SidebarCard
          title={null}
          tone="premium"
          minHeight={258}
          className="meesho-sidebar-card--extras"
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              marginBottom: 10,
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M12 3.8l2.37 4.8 5.3.78-3.84 3.74.91 5.28L12 15.9l-4.74 2.5.91-5.28-3.84-3.74 5.3-.78L12 3.8z"
                stroke={MEESHO_NEON.pink}
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
            </svg>
            <span
              style={{
                fontFamily: font,
                fontSize: 16,
                fontWeight: 800,
                color: brand.text,
                letterSpacing: "-0.2px",
              }}
            >
              Premium Features
            </span>
          </div>

          <p
            style={{
              margin: "0 0 12px",
              fontFamily: font,
              fontSize: 13,
              lineHeight: 1.45,
              color: brand.textMuted,
              display: "flex",
              alignItems: "center",
              flexWrap: "wrap",
              gap: "4px 8px",
            }}
          >
            <CoinIcon size={16} alt="" />
            <span>
              Premium billing:{" "}
              <span style={{ color: MEESHO_NEON.pinkSoft, fontWeight: 800 }}>
                {PREMIUM_CROP_COIN_COST_PER_LABEL} coin per label
              </span>{" "}
              when any premium option is enabled
            </span>
          </p>

          <div
            className="meesho-premium-balance-row"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap",
              gap: 10,
              padding: "10px 12px",
              borderRadius: 12,
              background: "rgba(11, 18, 32, 0.72)",
              border: "1px solid rgba(148, 163, 184, 0.2)",
              marginBottom: 12,
            }}
          >
            <div
              style={{
                minWidth: 0,
                display: "flex",
                alignItems: "center",
                gap: 8,
                flex: "1 1 120px",
              }}
            >
              <CoinIcon size={22} alt="" />
              <div
                style={{
                  fontFamily: font,
                  fontSize: "clamp(20px, 2.2vw, 28px)",
                  fontWeight: 800,
                  color: "#f6c453",
                  letterSpacing: "-0.6px",
                  lineHeight: 1,
                }}
              >
                {balance}
              </div>
              <span style={{ fontFamily: font, fontSize: 12.5, fontWeight: 700, color: "#f6c453" }}>
                coins
              </span>
            </div>
            <Link
              className="meesho-premium-topup"
              to="/wallet"
              style={{
                flexShrink: 0,
                display: "inline-flex",
                alignItems: "center",
                marginLeft: "auto",
                whiteSpace: "nowrap",
                padding: "7px 14px",
                borderRadius: 10,
                background: "rgba(21, 29, 48, 0.9)",
                border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
                color: MEESHO_NEON.pinkSoft,
                fontWeight: 700,
                fontSize: 12.5,
                fontFamily: font,
                textDecoration: "none",
                boxShadow: `inset 0 0 10px ${accent(0.12)}`,
              }}
            >
              Top up
            </Link>
          </div>

          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 6,
              padding: "10px 12px",
              borderRadius: 14,
              border: "1px solid rgba(148, 163, 184, 0.2)",
              background: "rgba(11, 18, 32, 0.62)",
            }}
          >
            <ToggleRow
              checked={detectSuspiciousBuyerEnabled}
              onToggle={() => setDetectSuspiciousBuyerEnabled((v) => !v)}
              label="Detect suspicious buyer"
            />
            <ToggleRow
              checked={Boolean(separateMultiOrderEnabled)}
              onToggle={() =>
                typeof setSeparateMultiOrderEnabled === "function"
                  ? setSeparateMultiOrderEnabled((v) => !v)
                  : null
              }
              label="Multi Orders by a Customer"
            />
            <ToggleRow
              checked={Boolean(loyalCustomerEnabled)}
              onToggle={() =>
                typeof setLoyalCustomerEnabled === "function"
                  ? setLoyalCustomerEnabled((v) => !v)
                  : null
              }
              label="Loyal Customer"
            />
            <ToggleRow
              checked={separatePincodesEnabled}
              onToggle={() => setSeparatePincodesEnabled((v) => !v)}
              label="Separate pincode"
            />
            {separatePincodesEnabled ? (
              <div
                style={{
                  marginTop: 4,
                  padding: "10px 10px 8px",
                  borderRadius: 12,
                  border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
                  background: accent(0.08),
                }}
              >
                <label
                  style={{
                    display: "block",
                    marginBottom: 6,
                    fontFamily: font,
                    fontSize: 12,
                    fontWeight: 700,
                    color: MEESHO_NEON.pinkSoft,
                  }}
                >
                  Pincodes to split (comma separated)
                </label>
                <div style={{ position: "relative" }}>
                  <textarea
                    ref={pincodeInputRef}
                    value={separatePincodes}
                    onChange={(e) => setSeparatePincodes(e.target.value)}
                    onScroll={(e) => {
                      if (!pincodeOverlayRef.current) return;
                      pincodeOverlayRef.current.scrollTop = e.target.scrollTop;
                      pincodeOverlayRef.current.scrollLeft = e.target.scrollLeft;
                    }}
                    placeholder=""
                    rows={3}
                    spellCheck={false}
                    style={{
                      width: "100%",
                      boxSizing: "border-box",
                      resize: "vertical",
                      borderRadius: 10,
                      border: "1px solid rgba(148,163,184,0.3)",
                      background: "rgba(11, 18, 32, 0.85)",
                      color: "transparent",
                      WebkitTextFillColor: "transparent",
                      caretColor: brand.text,
                      fontFamily: font,
                      fontSize: 13,
                      lineHeight: 1.4,
                      padding: "8px 10px",
                      outline: "none",
                      position: "relative",
                      zIndex: 2,
                    }}
                  />
                  <div
                    ref={pincodeOverlayRef}
                    aria-hidden
                    style={{
                      position: "absolute",
                      inset: 0,
                      borderRadius: 10,
                      overflow: "hidden",
                      padding: "8px 10px",
                      fontFamily: font,
                      fontSize: 13,
                      lineHeight: 1.4,
                      whiteSpace: "pre-wrap",
                      wordBreak: "break-word",
                      pointerEvents: "none",
                      zIndex: 3,
                      color: brand.text,
                    }}
                  >
                    {separatePincodes ? (
                      pincodeSegments.map((seg, idx) => (
                        <span
                          key={`pin-seg-${idx}`}
                          style={{
                            color: seg.invalid ? "#f59e0b" : brand.text,
                            fontWeight: seg.invalid ? 700 : 400,
                          }}
                        >
                          {seg.text}
                        </span>
                      ))
                    ) : (
                      <span style={{ color: "rgba(148, 163, 184, 0.75)" }}>
                        e.g. 110001, 400001, 560001
                      </span>
                    )}
                  </div>
                </div>
                <div
                  style={{
                    marginTop: 5,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    fontFamily: font,
                    fontSize: 11,
                  }}
                >
                  <span
                    style={{
                      color: brand.textDim,
                    }}
                  >
                    {pincodeValidation.state === "valid"
                      ? `${pincodeValidation.validCount} valid pincode${
                          pincodeValidation.validCount === 1 ? "" : "s"
                        }`
                      : pincodeValidation.state === "invalid"
                        ? `${pincodeValidation.invalidTokens.length} invalid value${
                            pincodeValidation.invalidTokens.length === 1 ? "" : "s"
                          } detected`
                        : "Enter comma-separated 6-digit pincodes"}
                  </span>
                  <span style={{ color: brand.textDim }}>{separatePincodes.length} characters</span>
                </div>
                {pincodeValidation.state === "invalid" ? (
                  <div
                    style={{
                      marginTop: 4,
                      fontFamily: font,
                      fontSize: 11.5,
                      color: brand.textDim,
                      lineHeight: 1.4,
                      wordBreak: "break-word",
                    }}
                  >
                    Incorrect:{" "}
                    {pincodeValidation.invalidTokens.map((token, idx) => (
                      <span key={`bad-pin-${token}-${idx}`}>
                        <span style={{ color: "#fb923c", fontWeight: 700 }}>{token}</span>
                        {idx < pincodeValidation.invalidTokens.length - 1 ? ", " : ""}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
            <UserHistoryPanel
              userHistorySuborderId={userHistorySuborderId}
              setUserHistorySuborderId={setUserHistorySuborderId}
            />
          </div>
        </SidebarCard>
      </div>
    </div>
  );
}

function UserHistoryPanel({ userHistorySuborderId, setUserHistorySuborderId }) {
  const navigate = useNavigate();
  const hasInput = Boolean(String(userHistorySuborderId || "").trim());

  const goToHistory = () => {
    const clean = String(userHistorySuborderId || "").trim();
    if (!clean) return;
    navigate(`/user-history?suborder_id=${encodeURIComponent(clean)}`);
    setUserHistorySuborderId("");
  };

  return (
    <div
      style={{
        marginTop: 4,
        padding: "10px 10px 8px",
        borderRadius: 12,
        border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
        background: "rgba(11, 18, 32, 0.85)",
      }}
    >
      <label
        style={{
          display: "block",
          marginBottom: 6,
          fontFamily: font,
          fontSize: 12,
          fontWeight: 700,
          color: MEESHO_NEON.pinkSoft,
        }}
      >
        See user history by Suborder ID
      </label>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="text"
          value={userHistorySuborderId}
          onChange={(e) => setUserHistorySuborderId(e.target.value)}
          placeholder="Enter suborder ID"
          onKeyDown={(e) => {
            if (e.key === "Enter" && hasInput) {
              e.preventDefault();
              goToHistory();
            }
          }}
          style={{
            flex: 1,
            minWidth: 0,
            borderRadius: 10,
            border: "1px solid rgba(148,163,184,0.3)",
            background: "rgba(11, 18, 32, 0.85)",
            color: brand.text,
            fontFamily: font,
            fontSize: 13,
            lineHeight: 1.4,
            padding: "8px 10px",
            outline: "none",
          }}
        />
        <button
          type="button"
          onClick={goToHistory}
          disabled={!hasInput}
          style={{
            padding: "8px 10px",
            borderRadius: 10,
            border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
            background: "rgba(21, 29, 48, 0.9)",
            color: brand.text,
            fontFamily: font,
            fontSize: 12,
            fontWeight: 700,
            cursor: !hasInput ? "not-allowed" : "pointer",
          }}
        >
          See history
        </button>
      </div>
    </div>
  );
}

function ToggleRow({ checked, onToggle, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={onToggle}
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        minHeight: 38,
        width: "100%",
        textAlign: "left",
        cursor: "pointer",
        border: checked
          ? `1.5px solid ${MEESHO_NEON.pink}`
          : `1.5px solid ${MEESHO_NEON.cardBorder}`,
        borderRadius: 12,
        background: checked ? accent(0.1) : "rgba(255,255,255,0.04)",
        padding: "8px 10px",
      }}
    >
      <span
        style={{
          fontFamily: font,
          fontSize: 13,
          color: checked ? brand.text : brand.textMuted,
          fontWeight: 600,
        }}
      >
        {label}
      </span>
      <span
        aria-hidden
        style={{
          width: 34,
          height: 20,
          borderRadius: 999,
          background: checked ? "rgba(236, 72, 153, 0.35)" : "rgba(148,163,184,0.25)",
          border: checked ? `1px solid ${MEESHO_NEON.pink}` : "1px solid rgba(148,163,184,0.35)",
          position: "relative",
          flexShrink: 0,
          transition: "all 0.15s",
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 2,
            left: checked ? 16 : 2,
            width: 14,
            height: 14,
            borderRadius: "50%",
            background: checked ? MEESHO_NEON.pink : "#cbd5e1",
            boxShadow: checked ? `0 0 8px ${MEESHO_NEON.pink}` : "none",
            transition: "left 0.15s",
          }}
        />
      </span>
    </button>
  );
}

function SidebarCard({ title, subtitle, tone, children, minHeight, className }) {
  const isPremium = tone === "premium";
  return (
    <section
      className={className}
      style={{
        position: "relative",
        borderRadius: 18,
        border: `1.5px solid ${isPremium ? MEESHO_NEON.cardBorderStrong : MEESHO_NEON.cardBorder}`,
        background: MEESHO_NEON.cardBg,
        padding: "14px 14px",
        boxShadow: isPremium
          ? `0 0 0 1px ${accent(0.18)}, 0 18px 40px ${accent(0.12)}`
          : "0 8px 24px rgba(0,0,0,0.25)",
        backdropFilter: "blur(8px)",
        minHeight,
        height: "100%",
      }}
    >
      {title ? (
        <h3
          style={{
            margin: 0,
            fontFamily: font,
            fontWeight: 800,
            fontSize: 14,
            color: brand.text,
            letterSpacing: "-0.2px",
          }}
        >
          {title}
        </h3>
      ) : null}
      {subtitle && (
        <p
          style={{
            margin: "4px 0 12px",
            fontFamily: font,
            fontSize: 12,
            color: brand.textMuted,
            lineHeight: 1.45,
          }}
        >
          {subtitle}
        </p>
      )}
      <div style={{ marginTop: subtitle ? 0 : 12 }}>{children}</div>
    </section>
  );
}

function CheckboxRow({ checked, onChange, label, help }) {
  return (
    <label
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "10px 12px",
        cursor: "pointer",
        border: checked
          ? `1.5px solid ${MEESHO_NEON.pink}`
          : `1.5px solid ${MEESHO_NEON.cardBorder}`,
        borderRadius: 12,
        background: checked ? accent(0.1) : "rgba(255,255,255,0.04)",
        transition: "all 0.15s",
      }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        style={{
          accentColor: MEESHO_NEON.pink,
          width: 15,
          height: 15,
          marginTop: 2,
          flexShrink: 0,
          cursor: "pointer",
        }}
      />
      <span
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 2,
          minWidth: 0,
        }}
      >
        <span
          style={{
            fontFamily: font,
            fontSize: 13,
            fontWeight: 700,
            color: checked ? brand.text : brand.textMuted,
            lineHeight: 1.35,
          }}
        >
          {label}
        </span>
        {help && (
          <span
            style={{
              fontFamily: font,
              fontSize: 11.5,
              color: brand.textDim,
              lineHeight: 1.4,
            }}
          >
            {help}
          </span>
        )}
      </span>
    </label>
  );
}

function FeatureStrip() {
  const items = [
    {
      icon: <FeatureBolt />,
      title: "Server-grade crop",
      desc: "Per-partner edges with millisecond-fast PyMuPDF.",
    },
    {
      icon: <FeatureLayers />,
      title: "Sort & dedupe",
      desc: "By Order ID, SKU, or delivery partner.",
    },
    {
      icon: <FeatureMerge />,
      title: "One merged PDF",
      desc: "Drop many invoices, get a single print-ready file.",
    },
    {
      icon: <FeatureShield />,
      title: "Coin-protected",
      desc: "Premium runs deduct only on success.",
    },
  ];
  return (
    <div
      className="meesho-feature-strip"
      style={{
        position: "relative",
        zIndex: 1,
        marginTop: 24,
        display: "grid",
        gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
        gap: 12,
      }}
    >
      {items.map((it) => (
        <div
          key={it.title}
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: 10,
            padding: "12px 12px",
            borderRadius: 14,
            border: `1px solid ${MEESHO_NEON.cardBorder}`,
            background: "rgba(20, 22, 30, 0.65)",
            backdropFilter: "blur(6px)",
          }}
        >
          <div style={{ flexShrink: 0, marginTop: 2 }}>{it.icon}</div>
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontFamily: font,
                fontSize: 13,
                fontWeight: 800,
                color: brand.text,
                marginBottom: 2,
                letterSpacing: "-0.1px",
              }}
            >
              {it.title}
            </div>
            <div
              style={{
                fontFamily: font,
                fontSize: 11.5,
                color: brand.textMuted,
                lineHeight: 1.4,
              }}
            >
              {it.desc}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function FeatureBolt() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M13 2L4 14h7l-1 8 10-12h-7l1-8z"
        stroke={MEESHO_NEON.pinkSoft}
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill={accent(0.16)}
      />
    </svg>
  );
}

function FeatureLayers() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 3l9 5-9 5-9-5 9-5z"
        stroke={brand.accentPurple}
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="rgba(167,139,250,0.15)"
      />
      <path
        d="M3 13l9 5 9-5"
        stroke={brand.accentPurple}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function FeatureMerge() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M6 3v6a4 4 0 004 4h4a4 4 0 014 4v4"
        stroke={brand.accentBlue}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="6" cy="3" r="1.5" fill={brand.accentBlue} />
      <circle cx="18" cy="21" r="1.5" fill={brand.accentBlue} />
    </svg>
  );
}

function FeatureShield() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"
        stroke={brand.accentCyan}
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="rgba(34,211,238,0.12)"
      />
    </svg>
  );
}

function TipRow() {
  return (
    <div
      style={{
        position: "relative",
        zIndex: 1,
        marginTop: 14,
        padding: "12px 16px",
        borderRadius: 14,
        border: `1px dashed ${MEESHO_NEON.cardBorderStrong}`,
        background: accent(0.06),
        display: "flex",
        alignItems: "center",
        gap: 10,
        fontFamily: font,
        fontSize: 12.5,
        color: brand.textMuted,
        lineHeight: 1.5,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 26,
          height: 26,
          borderRadius: 8,
          flexShrink: 0,
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          background: accent(0.18),
          border: `1px solid ${MEESHO_NEON.cardBorderStrong}`,
        }}
      >
        <span style={{ fontSize: 13 }}>💡</span>
      </span>
      <span>
        <strong style={{ color: brand.text }}>Tip:</strong> drop a single mixed PDF or many — the
        cropper de-duplicates pages and keeps your sort order. Multi-quantity invoices can be pushed
        to the end via Label Extras.
      </span>
    </div>
  );
}

const MeeshoNeonView = memo(MeeshoNeonViewImpl);
export default MeeshoNeonView;
