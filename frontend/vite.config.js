import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// WorkHire frontend — see Documentation/FRONTEND_DESIGN_SYSTEM.md for the
// design system this app implements. Dev server port is fixed at 5173 to
// match backend/.env.example's FRONTEND_URL (CORS + OAuth redirect depend on it).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // Lets the dev server answer through a Cloudflare quick tunnel
    // (localhost:5173 -> https://<random>.trycloudflare.com) for sharing a
    // live demo — Vite rejects unrecognized Host headers by default as a
    // DNS-rebinding guard. Fine for a temporary demo tunnel; remove if this
    // config is ever reused for something actually deployed.
    allowedHosts: [".trycloudflare.com"],
  },
});
