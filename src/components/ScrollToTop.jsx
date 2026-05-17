import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * Resets window scroll when the route changes so e.g. opening /flipkart
 * starts at the top of the workspace instead of keeping home-page scroll.
 */
export default function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    document.documentElement.scrollTop = 0;
    document.body.scrollTop = 0;
  }, [pathname]);

  return null;
}
