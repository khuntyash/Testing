export function UploadIcon({ size = 28, color }) {
  return (
    <svg width={size} height={size} fill="none" viewBox="0 0 24 24">
      <path
        d="M12 15V4m0 0-4 4m4-4 4 4"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M3 17v1a3 3 0 0 0 3 3h12a3 3 0 0 0 3-3v-1"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function CheckIcon({ size = 16 }) {
  return (
    <svg width={size} height={size} fill="none" viewBox="0 0 24 24">
      <path
        d="M5 13l4 4L19 7"
        stroke="white"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function GridIcon() {
  return (
    <svg width={14} height={14} fill="none" viewBox="0 0 24 24">
      <rect x="3" y="3" width="7" height="7" rx="1" fill="currentColor" opacity=".9" />
      <rect x="14" y="3" width="7" height="7" rx="1" fill="currentColor" opacity=".7" />
      <rect x="3" y="14" width="7" height="7" rx="1" fill="currentColor" opacity=".7" />
      <rect x="14" y="14" width="7" height="7" rx="1" fill="currentColor" opacity=".5" />
    </svg>
  );
}

export function ChevronDown({ size = 14 }) {
  return (
    <svg width={size} height={size} fill="none" viewBox="0 0 24 24">
      <path
        d="M6 9l6 6 6-6"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Open scissors — readable at small sizes on primary buttons (Lucide-style). */
export function ScissorsIcon({ size = 18, color = "#fff" }) {
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
      <circle cx="6" cy="6" r="3" fill="none" />
      <circle cx="6" cy="18" r="3" fill="none" />
      <line x1="20" y1="4" x2="8.12" y2="15.88" />
      <line x1="14.47" y1="14.48" x2="20" y2="20" />
      <line x1="8.12" y1="8.12" x2="12" y2="12" />
    </svg>
  );
}
