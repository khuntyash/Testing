import { useEffect, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext.jsx";
import AuthLeftPanel from "../components/AuthLeftPanel.jsx";
import "../../ZeroLabel.css";

export default function SignupPage() {
  const { isAuthenticated, signup, firebaseEnabled } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    document.body.classList.add("zerolabel-body");
    return () => document.body.classList.remove("zerolabel-body");
  }, []);

  if (isAuthenticated) return <Navigate to="/" replace />;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!name.trim()) return setError("Please enter your name.");
    if (password.length < 8) return setError("Password must be at least 8 characters.");
    if (password !== confirm) return setError("Passwords do not match.");
    setSubmitting(true);
    try {
      const result = await signup({ name: name.trim(), email: email.trim(), password });
      if (firebaseEnabled && result?.emailVerificationSent) {
        navigate("/login", {
          replace: true,
          state: { notice: "Account created. Please verify your email from inbox, then sign in." },
        });
        return;
      }
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create account.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-layout">
      <AuthLeftPanel />

      <section className="right-panel">
        <h2 className="form-title">Create Your Account</h2>
        <p className="form-sub">Start using ZeroLabel smart tools today</p>

        <div className="divider">Create account with email</div>

        <form onSubmit={handleSubmit} autoComplete="off">
          <div className="input-wrap">
            <span className="input-icon">
              <svg width="18" height="18" viewBox="0 0 24 24">
                <circle cx="12" cy="8" r="3.2" />
                <path d="M5.5 18.2c1.8-2.5 4.1-3.7 6.5-3.7s4.7 1.2 6.5 3.7" />
              </svg>
            </span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Enter your name" autoComplete="name" />
          </div>

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
              placeholder="Create a password"
              autoComplete="new-password"
            />
            <button className="eye-toggle" type="button" onClick={() => setShowPassword((v) => !v)}>
              <svg width="18" height="18" viewBox="0 0 24 24">
                <path d="M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>

          <div className="input-wrap">
            <span className="input-icon">
              <svg width="18" height="18" viewBox="0 0 24 24">
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </span>
            <input
              type={showConfirmPassword ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Confirm your password"
              autoComplete="new-password"
            />
            <button className="eye-toggle" type="button" onClick={() => setShowConfirmPassword((v) => !v)}>
              <svg width="18" height="18" viewBox="0 0 24 24">
                <path d="M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>

          {error ? <p style={{ color: "#fca5a5", marginBottom: 10, fontSize: "0.9rem" }}>{error}</p> : null}
          <button className="btn-create" type="submit" disabled={submitting}>
            {submitting ? "Creating..." : "Create Account"}
          </button>
        </form>

        <p className="sign-in-row">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </section>
    </div>
  );
}
