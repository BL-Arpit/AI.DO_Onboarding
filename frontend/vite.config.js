import { defineConfig } from "vite";
export default defineConfig({
  base: "/assets/react/",
  build: { outDir: "../app/static/react", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/assets/favicon.svg": "http://127.0.0.1:8000",
    },
  },
});
