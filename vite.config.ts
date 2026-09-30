import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    watch: {
      // Python environments and local model assets are not frontend inputs.
      // Watching them can consume more memory than the editing worker itself.
      ignored: ['**/.venv/**', '**/.audio-venv/**', '**/.alignment-venv/**',
        '**/asr-model/**', '**/audio-model/**', '**/alignment-model/**',
        '**/.test-artifacts/**', '**/src-tauri/**', '**/build/**', '**/release/**', '**/memory/**'],
    },
  },
});
