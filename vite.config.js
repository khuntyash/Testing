import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // Allow external tunnel tools like ngrok to forward requests
    allowedHosts: true,
    // Dev only: browser calls /api/... → your Python server (e.g. FastAPI on 8000)
    proxy: {
      "/api": {
        target: process.env.VITE_DEV_API_PROXY || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
