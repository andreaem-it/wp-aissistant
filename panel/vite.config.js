import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // Railway (and any host behind a reverse proxy) serves on a domain vite preview
  // doesn't recognize by default — allow any host rather than hardcoding Railway's.
  preview: { allowedHosts: true },
});
