import { defineConfig } from "vite"

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    /* Django on 8000. Same-origin in dev as in prod, so the DjangoAdapter's
       fetch("/api/…") never needs CORS or a base URL. */
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: false },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
})
