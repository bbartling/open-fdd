import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  esbuild: {
    target: "esnext",
  },
  optimizeDeps: {
    esbuildOptions: { target: "esnext" },
    holdUntilCrawlEnd: false,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: {
      "/api": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/openfdd-agent": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/config": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/ingest": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8765", changeOrigin: true },
      "/assets": { target: "http://127.0.0.1:8765", changeOrigin: true },
    },
  },
  build: {
    target: "esnext",
    outDir: "../api/static/app",
    emptyOutDir: true,
  },
});
