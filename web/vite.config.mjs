import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ["centro.aguirres.ca"],
    proxy: {
      "/api": {
        target: process.env.API_PROXY_TARGET || "http://api:8000",
        changeOrigin: true,
      },
      "/media": {
        target: process.env.API_PROXY_TARGET || "http://api:8000",
        changeOrigin: true,
      },
    },
  },
});
