/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The UI is served under BASE. The client calls BASE + "api/...", which the Vite proxy
// (dev) or nginx (cluster) forwards to nexus-api with that prefix stripped.
const BASE = "/nexus-ui/";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const nexusApi = env.VITE_NEXUS_API_URL || "http://localhost:5000";
  return {
    base: BASE,
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        [`${BASE}api`]: {
          target: nexusApi,
          changeOrigin: true,
          rewrite: (p) => p.slice(`${BASE}api`.length),
        },
      },
    },
    test: { environment: "jsdom", globals: true },
  };
});
