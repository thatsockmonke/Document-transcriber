import { defineConfig } from "vite";
export default defineConfig({
  base: process.env.SITE_BASE || "/Document-transcriber/",
  worker: { format: "es" },
  build: { target: "es2022", chunkSizeWarningLimit: 1600 },
});
