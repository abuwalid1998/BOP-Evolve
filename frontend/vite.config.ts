import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// `base: './'` keeps asset URLs relative so the same build works behind nginx
// and inside the Electron shell (app://bop-evolve/).
export default defineConfig({
  base: './',
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false, chunkSizeWarningLimit: 900 },
});
