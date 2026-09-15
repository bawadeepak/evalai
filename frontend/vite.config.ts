import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiPort = process.env.EVAL_TRIAGE_API_PORT ?? '8310'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 8311,
    strictPort: true,
    proxy: {
      '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
