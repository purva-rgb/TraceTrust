import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "^/(auth|batches|warehouses|inventory|products|operations|transfers|organizations|public|incidents)": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "^/labels$": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
