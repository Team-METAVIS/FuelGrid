import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: "dist", chunkSizeWarningLimit: 900 },
  server: { port: 5173, proxy: { "/api": "http://localhost:8080", "/metrics": "http://localhost:8080", "/docs": "http://localhost:8080" } },
});
