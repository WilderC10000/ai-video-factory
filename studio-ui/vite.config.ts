import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend (uvicorn, port 8000) serves /studio/*; Vite proxies to it in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/studio": "http://127.0.0.1:8000" },
  },
});
