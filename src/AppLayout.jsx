import { Outlet } from "react-router-dom";
import Header from "./components/Header.jsx";
import { useFonts } from "./hooks/useFonts.js";
import { brand, font, homeHeroBackground } from "./theme/brandTheme.js";

export default function AppLayout() {
  useFonts();

  return (
    <div style={{ fontFamily: font, minHeight: "100vh", background: homeHeroBackground, color: brand.text }}>
      <Header />
      <Outlet />
    </div>
  );
}
