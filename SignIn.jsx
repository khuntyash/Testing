import React, { useState } from 'react';
import './ZeroLabel.css';

const SignIn = () => {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <div className="auth-layout zerolabel-body">
      {/* ═══ LEFT PANEL ═══════════════════════════════════════ */}
      <section className="left-panel">
        <a className="logo" href="#">
          <div className="logo-icon">
            <svg viewBox="0 0 24 24" stroke="#a78bfa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
              <rect x="3" y="3" width="7" height="7" rx="1"/>
              <rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/>
              <path d="M14 17.5h7M17.5 14v7"/>
            </svg>
          </div>
          ZeroLabel
        </a>

        <p className="hero-label">Smart E-Commerce Tools</p>
        <h1 className="hero-title">
          <span className="pink">Meesho</span> &amp; <span className="blue">Flipkart</span><br />
          Label Cropping Made Easy
        </h1>
        <p className="hero-sub">
          Crop product labels from Meesho &amp; Flipkart,<br />
          detect suspicious buyers, and manage multiple<br />
          PDFs with smart detection technology.
        </p>

        {/* Feature cards */}
        <div className="cards-grid">
          <div className="card">
            <div className="card-icon icon-purple">
              <svg width="22" height="22" viewBox="0 0 24 24" stroke="#c4b5fd" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <rect x="3" y="3" width="18" height="18" rx="2"/>
                <path d="M9 3v18M15 3v18M3 9h18M3 15h18"/>
              </svg>
            </div>
            <div className="card-body">
              <h4>Label Cropping</h4>
              <p>Accurately crop product labels from Meesho &amp; Flipkart.</p>
              <span className="badge badge-purple">AI Powered</span>
            </div>
          </div>

          <div className="card">
            <div className="card-icon icon-pink">
              <svg width="22" height="22" viewBox="0 0 24 24" stroke="#f9a8d4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <path d="M12 2L4 6v6c0 5.25 3.5 10.15 8 11.35C17.5 22.15 21 17.25 21 12V6z"/>
              </svg>
            </div>
            <div className="card-body">
              <h4>Suspicious Buyer Detection</h4>
              <p>Smartly detect and flag suspicious buyers to protect your business.</p>
              <span className="badge badge-pink">Secure</span>
            </div>
          </div>

          <div className="card">
            <div className="card-icon icon-green">
              <svg width="22" height="22" viewBox="0 0 24 24" stroke="#86efac" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                <polyline points="14 2 14 8 20 8"/>
                <line x1="16" y1="13" x2="8" y2="13"/>
                <line x1="16" y1="17" x2="8" y2="17"/>
                <polyline points="10 9 9 9 8 9"/>
              </svg>
            </div>
            <div className="card-body">
              <h4>Multi PDF Support</h4>
              <p>Upload and manage multiple PDFs with ease.</p>
              <span className="badge badge-green">Bulk Processing</span>
            </div>
          </div>

          <div className="card">
            <div className="card-icon icon-blue">
              <svg width="22" height="22" viewBox="0 0 24 24" stroke="#93c5fd" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
              </svg>
            </div>
            <div className="card-body">
              <h4>Smart Detection</h4>
              <p>Advanced AI algorithms for high accuracy and speed.</p>
              <span className="badge badge-blue">Intelligent</span>
            </div>
          </div>
        </div>

        {/* Bottom bar */}
        <div className="bottom-bar">
          <div className="bottom-item">
            <div className="bottom-item-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <path d="M12 2L4 6v6c0 5.25 3.5 10.15 8 11.35C17.5 22.15 21 17.25 21 12V6z"/>
              </svg>
            </div>
            <div>
              <h5>Secure &amp; Private</h5>
              <p>Your data is encrypted and secure</p>
            </div>
          </div>
          <div className="bottom-item">
            <div className="bottom-item-icon">
              <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
              </svg>
            </div>
            <div>
              <h5>Fast Processing</h5>
              <p>Get results in seconds</p>
            </div>
          </div>
        </div>
      </section>

      {/* ═══ RIGHT PANEL ══════════════════════════════════════ */}
      <section className="right-panel">
        <h2 className="form-title">Welcome Back</h2>
        <p className="form-sub">Sign in to your ZeroLabel account</p>

        {/* Google */}
        <button className="social-btn">
          <img src="https://upload.wikimedia.org/wikipedia/commons/c/c1/Google_%22G%22_logo.svg" alt="Google logo" width="22" height="22" />
          Continue with Google
        </button>

        <div className="divider">or</div>

        {/* Email */}
        <div className="input-wrap">
          <span className="input-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
              <rect x="2" y="4" width="20" height="16" rx="2"/>
              <path d="M2 7l10 7 10-7"/>
            </svg>
          </span>
          <input type="email" placeholder="Enter your email" />
        </div>

        {/* Password */}
        <div className="input-wrap">
          <span className="input-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
              <rect x="3" y="11" width="18" height="11" rx="2"/>
              <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
            </svg>
          </span>
          <input 
            type={showPassword ? 'text' : 'password'} 
            placeholder="Enter your password" 
          />
          <button 
            className="eye-toggle" 
            onClick={() => setShowPassword(!showPassword)} 
            type="button"
            style={{ color: showPassword ? 'var(--purple-light)' : 'var(--muted)' }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
              <path d="M1 12S5 4 12 4s11 8 11 8-4 8-11 8S1 12 1 12z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
          </button>
        </div>

        {/* Forgot Password Link */}
        <div style={{ textAlign: 'right', marginBottom: '16px' }}>
          <a href="#" style={{ color: 'var(--muted)', fontSize: '0.85rem', textDecoration: 'none' }}>
            Forgot password?
          </a>
        </div>

        <button className="btn-create">Sign In</button>

        <p className="sign-in-row">Don't have an account? <a href="/signup">Sign up</a></p>

        <div className="terms">
          <svg width="16" height="16" viewBox="0 0 24 24" stroke="#6b7280" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
            <path d="M12 2L4 6v6c0 5.25 3.5 10.15 8 11.35C17.5 22.15 21 17.25 21 12V6z"/>
          </svg>
          <span>Protected by reCAPTCHA and subject to <a href="#">Privacy Policy</a></span>
        </div>
      </section>
    </div>
  );
};

export default SignIn;
