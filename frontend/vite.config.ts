import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // The backend (uv run uvicorn backend.app:app --port 8000) owns /ws in dev.
    proxy: {
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
