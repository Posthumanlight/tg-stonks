import { fileURLToPath, URL } from "node:url";

import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

// FastAPI dev server (poetry run uvicorn app.main:app --app-dir server --reload).
const API_ORIGIN = process.env["API_ORIGIN"] ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [preact()],
  resolve: {
    alias: {
      "@locales": fileURLToPath(new URL("../locales", import.meta.url)),
    },
  },
  server: {
    host: true, // reachable from a phone on the same network
    proxy: {
      "/api": API_ORIGIN,
      "/ws": { target: API_ORIGIN.replace(/^http/, "ws"), ws: true },
    },
    fs: { allow: [".."] }, // ../locales lives outside client/
  },
  build: {
    target: "es2022",
    chunkSizeWarningLimit: 2048, // Phaser alone is ~1.2 MB minified
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
});
