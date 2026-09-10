import { resolve } from 'path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const DEFAULT_EXTENSIONS = ['.mjs', '.js', '.ts', '.jsx', '.tsx', '.json']

export default defineConfig(() => {
  return {
    build: {
      outDir: '../cfdpuplink',
      emptyOutDir: true,
      rollupOptions: {
        input: 'src/main.js',
        output: {
          format: 'systemjs',
          hashCharacters: 'hex',
          entryFileNames: '[name].js',
          chunkFileNames: '[name]-[hash:20].js',
          assetFileNames: 'assets/[name]-[hash][extname]',
        },
        external: ['single-spa', 'vue', 'vuex', 'vue-router', 'vuetify'],
        preserveEntrySignatures: 'strict',
      },
    },
    server: {
      port: 2940,
    },
    plugins: [
      vue({
        template: {
          compilerOptions: {
            isCustomElement: (tag) => tag.startsWith('rux-'),
          },
        },
      }),
    ],
    resolve: {
      alias: {
        '@': resolve(__dirname, './src'),
      },
      extensions: [...DEFAULT_EXTENSIONS, '.vue'],
    },
    define: {
      __BASE_URL__: JSON.stringify('/tools/cfdpuplink'),
    },
    optimizeDeps: {
      entries: [],
    },
  }
})
