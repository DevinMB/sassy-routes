import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // '/beta/' for the staging build so its assets resolve under that prefix;
  // '/' for production. Runtime fetch('/api/...') is unaffected either way.
  base: process.env.VITE_BASE ?? '/',
  plugins: [react()],
  server: {
    proxy: {
      // dev only: talk to a locally running backend (uvicorn on :8000)
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
    },
  },
})
