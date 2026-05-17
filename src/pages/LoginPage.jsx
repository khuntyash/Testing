import { useEffect, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import AuthLeftPanel from "../components/AuthLeftPanel.jsx";
import "../../ZeroLabel.css";

export default function LoginPage() {
  const { isAuthenticated, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from && location.state.from !== "/login" ? location.state.from : "/";
  const noticeFromSignup = location.state?.notice || "";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState(noticeFromSignup);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    document.body.classList.add("zerolabel-body");
    return () => document.body.classList.remove("zerolabel-body");
  }, []);

  if (isAuthenticated) return <Navigate to="/" replace />;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign in failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-layout">
      <AuthLeftPanel />

      <section className="right-panel">
        <h2 className="form-title">Welcome Back</h2>
        <p className="form-sub">Sign in to your ZeroLabel account</p>

        <div className="divider">Sign in with email</div>

        <form onSubmit={handleSubmit} autoComplete="off">
          <input type="text" name="fake_username" autoComplete="username" style={{ display: "none" }} />
          <input type="password" name="fake_password" autoComplete="current-password" style={{ display: "none" }} />
          <div className="input-wrap">
            <span className="input-icon">
              <svg width="18" height="18" viewBox="0 0 24 24">
                <rect x="2" y="4" width="20" height="16" rx="2" />
                <path d="M2 7l10 7 10-7" />
              </svg>
            </span>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="Enter your email"
              autoComplete="off"
            />
          </div>

          <div className="input-wrap">
            <span className="input-icon">
              <svg width="18" height="18" viewBox="0 0 24 24">
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </span>
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your password"
              autoComplete="new-password"
            />
            <button className="eye-toggle" type="button" onClick={() => setShowPassword((v) => !v)}>
              <svg width="18" height="18" viewBox="0 0 24 24">
                <path d="M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>

          {error ? <p style={{ color: "#fca5a5", marginBottom: 10, fontSize: "0.9rem" }}>{error}</p> : null}
          <button className="btn-create" type="submit" disabled={submitting}>
            {submitting ? "Signing in..." : "Sign In"}
          </button>
        </form>

        <p className="sign-in-row">
          Don't have an account? <Link to="/signup">Sign up</Link>
        </p>
      </section>
    </div>
  );
}
