import React from "react";

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "", stack: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : String(error || "Unknown error"),
    };
  }

  componentDidCatch(error, info) {
    this.setState({
      stack: (info && info.componentStack ? String(info.componentStack) : "").trim(),
    });
    // Keep this in console for easier debugging in browser devtools.
    // eslint-disable-next-line no-console
    console.error("Unhandled UI error:", error, info);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    const showStack = Boolean(import.meta.env.DEV) && Boolean(this.state.stack);

    return (
      <div
        role="alert"
        style={{
          minHeight: "100vh",
          background: "#0f172a",
          color: "#e2e8f0",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif",
        }}
      >
        <div
          style={{
            width: "100%",
            maxWidth: 860,
            border: "1px solid rgba(148, 163, 184, 0.3)",
            borderRadius: 14,
            background: "rgba(15, 23, 42, 0.92)",
            boxShadow: "0 16px 40px rgba(0,0,0,0.3)",
            padding: 20,
          }}
        >
          <h2 style={{ margin: "0 0 8px", fontSize: 22, color: "#f8fafc" }}>Something went wrong</h2>
          <p style={{ margin: "0 0 14px", color: "#cbd5e1", lineHeight: 1.45 }}>
            The page crashed while rendering. Refresh to retry.
          </p>
          <div
            style={{
              background: "rgba(30, 41, 59, 0.8)",
              border: "1px solid rgba(148, 163, 184, 0.25)",
              borderRadius: 10,
              padding: 12,
              color: "#fda4af",
              fontSize: 13,
              wordBreak: "break-word",
            }}
          >
            {this.state.message || "Unknown rendering error"}
          </div>
          {showStack ? (
            <pre
              style={{
                marginTop: 10,
                maxHeight: 220,
                overflow: "auto",
                background: "rgba(2, 6, 23, 0.75)",
                border: "1px solid rgba(148, 163, 184, 0.2)",
                borderRadius: 8,
                padding: 10,
                fontSize: 11.5,
                color: "#93c5fd",
                whiteSpace: "pre-wrap",
              }}
            >
              {this.state.stack}
            </pre>
          ) : null}
          <button
            type="button"
            onClick={this.handleReload}
            style={{
              marginTop: 14,
              padding: "10px 14px",
              borderRadius: 8,
              border: "1px solid rgba(125, 211, 252, 0.5)",
              background: "rgba(59, 130, 246, 0.2)",
              color: "#e0f2fe",
              cursor: "pointer",
              fontWeight: 700,
            }}
          >
            Reload page
          </button>
        </div>
      </div>
    );
  }
}

export default AppErrorBoundary;
