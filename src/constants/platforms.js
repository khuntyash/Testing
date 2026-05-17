export const PLATFORMS = [
  {
    id: "meesho",
    name: "Meesho",
    color: "#9B1FC6",
    bg: "#FAF0FF",
    border: "#DDB4FC",
    abbr: "ME",
    orders: 234,
    trend: "+12%",
    logo: "/platforms/meesho.svg",
    /** Raster logo for large home CTA tiles (public/platforms). */
    homeThumbnail: "/platforms/meesho%20logo.png",
  },
  {
    id: "flipkart",
    name: "Flipkart",
    color: "#2874F0",
    bg: "#F0F5FF",
    border: "#AABFFA",
    abbr: "FK",
    orders: 445,
    trend: "+19%",
    logo: "/platforms/flipkart.svg",
    homeThumbnail: "/platforms/Flipkart%20logo.png",
  },
];

/** Output format options used by crop workspace UI. */
export const OUTPUT_LAYOUTS = [
  {
    value: "label_printer",
    label: "Label Cropper",
    hint: "Thermal or roll labels (e.g. 4×6). Best for couriers.",
    icon: "🖨",
  },
  {
    value: "keep_invoice",
    label: "Label with Invoice",
    hint: "Keep original invoice pages in output.",
    icon: "📋",
  },
];

export const SORT_OPTIONS = [
  { value: "order_id", label: "Default / Order ID", icon: "⊟" },
  { value: "sku", label: "SKU", icon: "⊞" },
  { value: "delivery", label: "Sort by delivery partner", icon: "⊕" },
];

/** @param {string} id */
export function getPlatformById(id) {
  return PLATFORMS.find((p) => p.id === id) ?? null;
}
