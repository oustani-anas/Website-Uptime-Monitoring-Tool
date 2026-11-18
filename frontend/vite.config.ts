import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Local development (`npm run dev`) talks to the API container directly.
    // In Docker, nginx does this proxying instead (see nginx.conf).
    proxy: { "/api": "http://localhost:8000" },
  },
});
