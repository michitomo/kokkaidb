import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    include: [
      'src/**/__tests__/**/*.{ts,tsx,js,jsx}',
      'scripts/__tests__/**/*.{ts,tsx}',
    ],
  },
  resolve: {
    alias: {
      // scripts/ からの相対インポートを解決する
      '../../scripts/generate-api': resolve(__dirname, 'scripts/generate-api.ts'),
      '../../../scripts/generate-api': resolve(__dirname, 'scripts/generate-api.ts'),
    },
  },
});
