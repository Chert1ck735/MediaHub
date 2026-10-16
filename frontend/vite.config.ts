import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Бэкенд: uvicorn backend.app.main:app --reload → http://127.0.0.1:8000
// Можно переопределить адрес бэка переменной окружения VITE_BACKEND_TARGET
// (полезно, если uvicorn запущен на другом хосте/порту).
const BACKEND_TARGET = process.env.VITE_BACKEND_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // host: true — Vite слушает 0.0.0.0, заходить с любого устройства в LAN
    // по http://<ip-машины>:5173. /api проксируется в uvicorn.
    allowedHosts: true,
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
    },
  },
  preview: {
    // vite preview — отдача собранного билда тоже на 0.0.0.0
    allowedHosts: true,
    host: true,
    port: 4173,
    strictPort: true,
  },
});
