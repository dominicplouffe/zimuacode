/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const server = process.env.ZIMUA_SERVER ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  // Monaco alone is several MB; it is bundled on purpose so the editor works offline.
  build: { chunkSizeWarningLimit: 6000 },
  server: {
    port: 5173,
    // Same origin as the API in development, so the session cookie just works.
    proxy: { '/api': { target: server, changeOrigin: false, ws: true } },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
