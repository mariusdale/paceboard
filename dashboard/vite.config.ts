import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_PORT = process.env.PACEBOARD_API_PORT ?? "8787";
const WEB_PORT = Number(process.env.PACEBOARD_WEB_PORT ?? 3000);

export default defineConfig({
  plugins: [react()],
  server: {
    // Loopback only. The dashboard renders personal health data and must not be
    // reachable from the network by default.
    host: "127.0.0.1",
    port: WEB_PORT,
    strictPort: true,
    // The browser talks only to this origin; Vite forwards /api to the backend,
    // so no Garmin or Strava credential ever reaches the page.
    proxy: {
      "/api": { target: `http://127.0.0.1:${API_PORT}`, changeOrigin: true },
      "/healthz": { target: `http://127.0.0.1:${API_PORT}`, changeOrigin: true },
    },
  },
  preview: { host: "127.0.0.1", port: WEB_PORT, strictPort: true },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // Recharts is by far the largest dependency and changes rarely; keeping
        // it in its own chunk keeps the app chunk small and cacheable.
        manualChunks: {
          charts: ["recharts"],
          vendor: ["react", "react-dom", "react-router-dom", "@tanstack/react-query"],
        },
      },
    },
  },
});
