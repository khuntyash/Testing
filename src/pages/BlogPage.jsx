import { brand, font, homeHeroBackground } from "../theme/brandTheme.js";

const BLOG_POSTS = [
  {
    title: "7 E-commerce Shipping Strategies That Cut Returns",
    tag: "Operations",
    readTime: "6 min read",
    excerpt:
      "Reduce failed deliveries by pairing courier rules, clean address capture, and smarter dispatch windows.",
  },
  {
    title: "How Fast Label Processing Improves Seller Ratings",
    tag: "Growth",
    readTime: "5 min read",
    excerpt:
      "Consistent same-day dispatch and accurate labels reduce support tickets and improve marketplace trust signals.",
  },
  {
    title: "Courier Partner Selection: Cost vs Delivery Experience",
    tag: "Logistics",
    readTime: "8 min read",
    excerpt:
      "Choose between low-cost and premium carriers by pincode clusters, COD patterns, and return-risk scores.",
  },
  {
    title: "Building a Repeat-Purchase Loop for D2C Stores",
    tag: "Retention",
    readTime: "7 min read",
    excerpt:
      "Use post-delivery WhatsApp nudges, reorder reminders, and personalized bundles to increase LTV.",
  },
];

export default function BlogPage() {
  return (
    <div
      style={{
        minHeight: "calc(100vh - 64px)",
        background: homeHeroBackground,
        padding: "28px 24px 56px",
        fontFamily: font,
        color: brand.text,
      }}
    >
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        <p
          style={{
            margin: "0 0 8px",
            fontSize: 12,
            fontWeight: 700,
            color: brand.accentBlue,
            letterSpacing: "0.08em",
          }}
        >
          BLOG · E-COMMERCE
        </p>
        <h1
          style={{
            margin: "0 0 12px",
            fontSize: "clamp(24px, 3.2vw, 34px)",
            fontWeight: 800,
            color: brand.text,
            letterSpacing: "-0.6px",
          }}
        >
          E-commerce growth and operations insights
        </h1>
        <p
          style={{
            margin: "0 0 30px",
            fontSize: 15,
            color: brand.textMuted,
            lineHeight: 1.6,
            maxWidth: 760,
          }}
        >
          Practical articles on shipping, label workflows, courier strategy, retention, and scale for
          marketplace and D2C sellers.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 18 }}>
          {BLOG_POSTS.map((post) => (
            <article
              key={post.title}
              style={{
                border: `1px solid ${brand.border}`,
                borderRadius: 16,
                background: brand.bgCard,
                backdropFilter: "blur(8px)",
                padding: "18px 16px 16px",
                boxShadow: "0 10px 28px rgba(0,0,0,0.16)",
              }}
            >
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "5px 10px",
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.04em",
                  color: brand.accentPurple,
                  background: "rgba(124, 58, 237, 0.12)",
                  border: "1px solid rgba(124, 58, 237, 0.25)",
                  marginBottom: 12,
                }}
              >
                {post.tag}
              </div>
              <h2
                style={{
                  margin: "0 0 10px",
                  fontSize: 19,
                  lineHeight: 1.3,
                  fontWeight: 800,
                  color: brand.text,
                  letterSpacing: "-0.2px",
                }}
              >
                {post.title}
              </h2>
              <p style={{ margin: "0 0 14px", fontSize: 14, color: brand.textMuted, lineHeight: 1.55 }}>
                {post.excerpt}
              </p>
              <div style={{ fontSize: 12, fontWeight: 600, color: brand.textDim }}>{post.readTime}</div>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

