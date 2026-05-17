/**
 * Shared coin artwork (`/coin-icon.png`) for wallet, premium UI, and marketing copy.
 */
export default function CoinIcon({ size = 20, style, className, alt = "Coins", title }) {
  return (
    <img
      src="/coin-icon.png"
      alt={alt}
      title={title}
      width={size}
      height={size}
      className={className}
      style={{
        width: size,
        height: size,
        objectFit: "contain",
        display: "inline-block",
        verticalAlign: "middle",
        flexShrink: 0,
        ...style,
      }}
      draggable={false}
    />
  );
}
