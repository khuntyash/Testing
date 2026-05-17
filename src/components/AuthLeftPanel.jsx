export default function AuthLeftPanel() {
  return (
    <section className="left-panel">
      <a className="logo" href="#">
        <div className="logo-icon">
          <svg viewBox="0 0 24 24">
            <rect x="3" y="3" width="7" height="7" rx="1" />
            <rect x="14" y="3" width="7" height="7" rx="1" />
            <rect x="3" y="14" width="7" height="7" rx="1" />
            <path d="M14 17.5h7M17.5 14v7" />
          </svg>
        </div>
        ZeroLabel
      </a>

      <p className="hero-label">Smart E-Commerce Tools</p>
      <h1 className="hero-title">
        <span className="pink">Meesho</span> &amp; <span className="blue">Flipkart</span>
        <br />
        Label Cropping Made Easy
      </h1>
      <p className="hero-sub">
        Crop product labels from Meesho &amp; Flipkart,
        <br />
        detect suspicious buyers, and manage multiple
        <br />
        PDFs with smart detection technology.
      </p>

      <div className="cards-grid">
        <div className="card">
          <div className="card-icon icon-purple">
            <svg width="22" height="22" viewBox="0 0 24 24">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M9 3v18M15 3v18M3 9h18M3 15h18" />
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
            <svg width="22" height="22" viewBox="0 0 24 24">
              <path d="M12 2L4 6v6c0 5.25 3.5 10.15 8 11.35C17.5 22.15 21 17.25 21 12V6z" />
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
            <svg width="22" height="22" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
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
            <svg width="22" height="22" viewBox="0 0 24 24">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
          </div>
          <div className="card-body">
            <h4>Smart Detection</h4>
            <p>Advanced AI algorithms for high accuracy and speed.</p>
            <span className="badge badge-blue">Intelligent</span>
          </div>
        </div>
      </div>
    </section>
  );
}
