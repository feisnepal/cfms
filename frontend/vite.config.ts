import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

/**
 * Stamp public/sw.js with this build's id. A service worker is updated by the browser only when the bytes of the file change; the id changes them on every release.
 * (The worker itself is a plain file in public/, copied unchanged by Vite.)
 */
function serviceWorkerBuildId(): Plugin {
  let outDir = 'dist'
  let root = process.cwd()
  return {
    name: 'cf-service-worker-build-id',
    apply: 'build',
    configResolved(config) { outDir = config.build.outDir; root = config.root },
    closeBundle() {
      const file = resolve(root, outDir, 'sw.js')
      if (!existsSync(file)) return
      writeFileSync(file, readFileSync(file, 'utf-8').replace('__BUILD_ID__', new Date().toISOString()))
    },
  }
}

export default defineConfig({
  plugins: [react(), serviceWorkerBuildId()],
  server: {
    port: 3001,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        timeout: 600000,
        proxyTimeout: 600000,
        secure: false,
      }
    }
  },
  build: {
    target: 'es2020',
    // S2-42 (hardening 4.7): 648 console.* calls ship to production, including a
    // request interceptor logging every API URL (calculation UUIDs + query
    // strings end up in consoles, screenshots, support tickets). Vite 8 minifies
    // with the Oxc minifier, where the esbuild-era `esbuild.drop` key is a no-op
    // — the canonical surface is the minifier's `dropConsole` option. Deliberate
    // Sentry reporting goes through the `logger`/Sentry modules, never console.
    rolldownOptions: {
      output: {
        minify: {
          compress: {
            dropConsole: true,
          },
        },
      },
    },
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (id.includes('node_modules/react-dom') || id.includes('node_modules/react/') || id.includes('node_modules/react-router')) return 'vendor-react'
          if (id.includes('node_modules/antd') || id.includes('node_modules/@ant-design')) return 'vendor-ui'
          if (id.includes('node_modules/@tanstack/react-query')) return 'vendor-query'
          if (id.includes('node_modules/chart.js') || id.includes('node_modules/react-chartjs')) return 'charts'
          if (id.includes('node_modules/leaflet') || id.includes('node_modules/react-leaflet')) return 'vendor-map'
          if (id.includes('node_modules/@turf') || id.includes('node_modules/proj4')) return 'geospatial'
          if (id.includes('node_modules/@sentry') || id.includes('node_modules/web-vitals')) return 'vendor-monitor'
        }
      }
    }
  },
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom', 'antd', 'leaflet', 'chart.js', '@turf/turf'],
  }
})
