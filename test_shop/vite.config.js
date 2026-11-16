import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to a running `node server.js` (port 3010); the benchmark uses the build.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:3010" } },
  build: { outDir: "dist", emptyOutDir: true },
});
