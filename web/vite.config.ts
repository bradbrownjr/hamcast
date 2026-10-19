import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Builds into the Python package, which serves it (hamcast/web.py).
// `npm run dev` proxies the API to a hamcast running on :8080.
export default defineConfig({
  plugins: [react()],
  build: { outDir: '../hamcast/static', emptyOutDir: true, chunkSizeWarningLimit: 800 },
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/recordings': 'http://localhost:8080',
    },
  },
});
