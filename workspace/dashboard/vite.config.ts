import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  build: {
    outDir: process.env.VITE_OUT_DIR || "dist",
    emptyOutDir: true,
  },
  server: {
    port: Number(process.env.VITE_DEV_PORT || 5173),
    host: process.env.VITE_DEV_HOST || "127.0.0.1",
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8080", changeOrigin: true },
      "/openfdd-agent": { target: "http://127.0.0.1:8080", changeOrigin: true },
    },
  },
});
