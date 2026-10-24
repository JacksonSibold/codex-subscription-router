import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const version = readFileSync(resolve(root, 'VERSION'), 'utf8').trim();

export default defineConfig({
  plugins: [react()],
  define: {
    __RELAY_VERSION__: JSON.stringify(version),
  },
  server: {
    host: '127.0.0.1',
    port: 7100,
    strictPort: false,
    proxy: {
      '/api': `http://127.0.0.1:${process.env.CODEX_ROUTER_MANAGER_PORT || '18766'}`,
    },
  },
});
