import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // dev only: talk to a locally running backend (uvicorn on :8000)
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
    },
  },
})
