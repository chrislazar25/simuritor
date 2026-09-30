import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // The static demo (VITE_STATIC=1) is served under a subpath on GitHub Pages, e.g. VITE_BASE=/simuritor-demo/.
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  worker: { format: 'es' },
  server: {
    // The backend (uv run uvicorn backend.app:app --port 8000) owns /ws and /api in dev.
    proxy: {
      '/ws': { target: 'ws://localhost:8000', ws: true },
      '/api': 'http://localhost:8000',
    },
  },
})
