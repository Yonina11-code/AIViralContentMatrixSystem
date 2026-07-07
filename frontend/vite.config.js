import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5170,
    proxy: {
      '/api': {
        target: 'http://localhost:5177',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:5177',
        changeOrigin: true,
      },
      '/static': {
        target: 'http://localhost:5177',
        changeOrigin: true,
      },
    },
  },
})
