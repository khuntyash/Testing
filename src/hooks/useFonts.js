import { useEffect } from "react";

const MONTSERRAT =
  "https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700;800&display=swap";

export function useFonts() {
  useEffect(() => {
    const link = document.createElement("link");
    link.href = MONTSERRAT;
    link.rel = "stylesheet";
    document.head.appendChild(link);
    return () => {
      try {
        document.head.removeChild(link);
      } catch {
        /* ignore */
      }
    };
  }, []);
}
