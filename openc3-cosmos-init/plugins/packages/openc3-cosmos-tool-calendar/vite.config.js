/*
###############################################################################
# Copyright (c) ATTX, Inc. 2026. All Rights Reserved.
#
# This software and associated documentation (the "Software") are the
# proprietary and confidential information of ATTX, Inc. The Software is
# furnished under a license agreement between ATTX and the user organization
# and may be used or copied only in accordance with the terms of the agreement.
# Refer to 'license/attx_license.adoc' for standard license terms.
#
# EXPORT CONTROL NOTICE: THIS SOFTWARE MAY INCLUDE CONTENT CONTROLLED UNDER THE
# INTERNATIONAL TRAFFIC IN ARMS REGULATIONS (ITAR) OR THE EXPORT ADMINISTRATION
# REGULATIONS (EAR99). No part of the Software may be used, reproduced, or
# transmitted in any form or by any means, for any purpose, without the express
# written permission of ATTX, Inc.
###############################################################################
*/

import { resolve } from 'path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { devServerPlugin } from '@openc3/js-common/viteDevServerPlugin'

const DEFAULT_EXTENSIONS = ['.mjs', '.js', '.ts', '.jsx', '.tsx', '.json']

export default defineConfig((options) => {
  return {
    build: {
      outDir: 'tools/calendar',
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
      port: 2924,
    },
    plugins: [
      vue({
        template: {
          compilerOptions: {
            isCustomElement: (tag) => tag.startsWith('rux-'),
          },
        },
      }),
      devServerPlugin(options),
    ],
    resolve: {
      alias: {
        '@': resolve(__dirname, './src'),
      },
      extensions: [...DEFAULT_EXTENSIONS, '.vue'], // not recommended but saves us from having to change every SFC import
    },
    define: {
      __BASE_URL__: JSON.stringify('/tools/calendar'),
    },
    optimizeDeps: {
      entries: [], // https://github.com/vituum/vituum/issues/25#issuecomment-1690080284
    },
  }
})
