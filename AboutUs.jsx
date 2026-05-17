import { useEffect } from "react";
import { Link } from "react-router-dom";
import './ZeroLabel.css';

const AboutUs = () => {
  useEffect(() => {
    document.body.classList.add("zerolabel-body");
    return () => document.body.classList.remove("zerolabel-body");
  }, []);

  return (
    <div>
      {/* ── HERO SECTION ────────────────────────────────── */}
      <section className="hero-full">
        <p className="hero-label">About ZeroLabel</p>
        <h1 className="hero-title">Zero Friction, <span className="gradient">Total Control</span></h1>
        <p className="hero-sub">
          In the fast-paced world of Indian e-commerce, a shipping label is more than just a piece of paper—it is the lifeline of your fulfillment process.
        </p>
      </section>

      {/* ── MAIN CONTENT ────────────────────────────────── */}
      <main className="about-container">
        
        {/* Mission */}
        <section className="mission">
          <div className="mission-text">
            <h2>The Mission</h2>
            <p>
              ZeroLabel was born out of a simple necessity: to eliminate the hours wasted on manual PDF editing and the thousands of rupees lost to fraudulent orders and RTO (Return to Origin) mishaps.
            </p>
            <p>
              We believe that high-volume sellers shouldn't be held back by messy logistics. Our platform is designed to turn your daily invoice batches into a streamlined, data-driven operation.
            </p>
          </div>
          <div className="mission-image">
            <svg viewBox="0 0 24 24" stroke="#7c3aed" opacity="0.8" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
          </div>
        </section>

        {/* Core Values */}
        <h2 className="section-title">What Makes Us Different?</h2>
        <div className="cards-grid about-grid">
          <div className="card about-card">
            <div className="card-icon icon-purple">
              <svg width="28" height="28" viewBox="0 0 24 24" stroke="#c4b5fd" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
              </svg>
            </div>
            <h3>Intelligent Automation</h3>
            <p>We don't just crop; we understand. Whether it’s Flipkart, Delhivery, or Valmo, our system identifies partners and SKUs instantly to organize your workflow before you even hit 'Print'.</p>
          </div>
          {/* Fraud Protection */}
          <div className="card about-card">
            <div className="card-icon icon-pink">
              <svg width="28" height="28" viewBox="0 0 24 24" stroke="#f9a8d4" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
              </svg>
            </div>
            <h3>Fraud Protection</h3>
            <p>We help you spot "serial returners" and suspicious purchasing patterns before you ship. By detecting high-risk buyers, ZeroLabel empowers you to save on logistics costs and reduce your RTO rate.</p>
          </div>

          <div className="card about-card">
            <div className="card-icon icon-blue">
              <svg width="28" height="28" viewBox="0 0 24 24" stroke="#93c5fd" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
              </svg>
            </div>
            <h3>Strategic Sorting</h3>
            <p>From separating multi-quantity orders to grouping labels by pincodes, we optimize your warehouse floor for speed. Your team spends less time walking and more time packing.</p>
          </div>

          <div className="card about-card">
            <div className="card-icon icon-green">
              <svg width="28" height="28" viewBox="0 0 24 24" stroke="#86efac" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
                <path d="M2 16.1A5 5 0 0 1 5.9 20M2 12.05A9 9 0 0 1 9.95 20M2 8V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"/>
                <line x1="2" y1="20" x2="2.01" y2="20"/>
              </svg>
            </div>
            <h3>Data-Driven Growth</h3>
            <p>We bridge the gap between your shipping labels and your long-term success. By analyzing customer churn and return trends, we give you the insights needed to scale your brand with confidence.</p>
          </div>
        </div>

        {/* Advantage Section */}
        <section className="mission mission-reverse" style={{ marginTop: 'clamp(80px, 12vw, 160px)' }}>
          <div className="mission-text">
            <h2>The ZeroLabel Advantage<br/><span style={{ fontSize: '0.6em', color: 'var(--muted)', fontWeight: 700 }}>A System That Learns</span></h2>
            <p>
              The true power of ZeroLabel is that it gets smarter every single day you use it. Unlike basic tools that reset every time you close them, our platform builds a <strong>Living Database</strong> of your business operations.
            </p>
            
            <div style={{ marginTop: 'clamp(24px, 4vw, 40px)', display: 'flex', flexDirection: 'column', gap: 'clamp(16px, 2vw, 24px)' }}>
              <div>
                <h4 style={{ color: 'var(--purple-light)', fontSize: 'clamp(1.1rem, 1.3vw, 1.3rem)', marginBottom: '4px' }}>Growing Intelligence</h4>
                <p style={{ fontSize: 'clamp(0.9rem, 1.1vw, 1.1rem)', marginBottom: 0, color: 'var(--muted)', lineHeight: 1.6 }}>
                  Every label scanned and every RTO sheet uploaded helps the system refine its "Suspicious Buyer" detection. It learns the specific patterns of your customers and your niche.
                </p>
              </div>
              <div>
                <h4 style={{ color: 'var(--pink)', fontSize: 'clamp(1.1rem, 1.3vw, 1.3rem)', marginBottom: '4px' }}>Historical Memory</h4>
                <p style={{ fontSize: 'clamp(0.9rem, 1.1vw, 1.1rem)', marginBottom: 0, color: 'var(--muted)', lineHeight: 1.6 }}>
                  Over time, ZeroLabel identifies repeat buyers and "problem" pincodes specific to your brand, allowing you to make proactive shipping decisions that save your margins.
                </p>
              </div>
              <div>
                <h4 style={{ color: 'var(--blue)', fontSize: 'clamp(1.1rem, 1.3vw, 1.3rem)', marginBottom: '4px' }}>Evolving Performance</h4>
                <p style={{ fontSize: 'clamp(0.9rem, 1.1vw, 1.1rem)', marginBottom: 0, color: 'var(--muted)', lineHeight: 1.6 }}>
                  As your data grows, our churn analysis becomes more precise, helping you predict which customers are likely to stay and which are likely to leave, long before it happens.
                </p>
              </div>
            </div>
          </div>
          
          <div className="mission-image" style={{ boxShadow: '0 0 80px rgba(124,58,237,0.15)', borderColor: 'rgba(124,58,237,0.3)' }}>
            <svg viewBox="0 0 24 24" stroke="#e91e8c" opacity="0.9" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none">
               <circle cx="12" cy="12" r="10"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/><path d="M2 12h20"/>
            </svg>
          </div>
        </section>

      </main>

      {/* ── CTA ─────────────────────────────────────────── */}
      <section className="cta-section">
        <p className="hero-label" style={{ justifyContent: 'center', display: 'flex', marginBottom: '12px' }}>Our Vision for the Future</p>
        <h2>Zero Errors, Zero Waste, Zero Stress</h2>
        <p style={{ maxWidth: '800px', margin: '0 auto clamp(32px, 4vw, 48px)', lineHeight: 1.6 }}>
          We are building the brain of the modern warehouse. By integrating historical order data with real-time logistics intelligence, ZeroLabel is dedicated to helping e-commerce sellers achieve flawless operations.
        </p>
        <Link to="/signup" className="cta-btn">Join ZeroLabel Today</Link>
      </section>

    </div>
  );
};

export default AboutUs;
