import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import type { IncomingMessage } from "http";

const apiTarget = process.env.VITE_API_TARGET ?? "http://localhost:8000";

const apiRoutes = [
  "/api",
  "/ai",
  "/sites",
  "/equipment",
  "/points",
  "/timeseries",
  "/faults",
  "/run-fdd",
  "/download",
  "/capabilities",
  "/config",
  "/data-model",
  "/entities",
  "/jobs",
  "/bacnet",
  "/analytics",
  "/health",
  "/docs",
  "/redoc",
  "/openapi.json",
  "/rules",
];

/** Serve the SPA for browser navigation; proxy only fetch/XHR to the API. */
function spaBypass(req: IncomingMessage) {
  if (req.headers.accept?.includes("text/html")) {
    return "/index.html";
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  server: {
    host: "0.0.0.0",
    allowedHosts: ["localhost", ".local"],
    proxy: {
      ...Object.fromEntries(
        apiRoutes.map((r) => [r, { target: apiTarget, bypass: spaBypass }]),
      ),
      "/ws": { target: apiTarget, ws: true },
    },
  },
});
