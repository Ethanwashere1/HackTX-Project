import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
      "/agents": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/agents/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
    fileParallelism: false,
  },
});
