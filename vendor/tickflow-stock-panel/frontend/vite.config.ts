import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

const basePath = (() => {
  const raw = process.env.VITE_BASE_PATH || '/'
  return raw.endsWith('/') ? raw : `${raw}/`
})()

const proxyTarget = 'http://localhost:3018'
const apiPath = new URL('api', `http://localhost${basePath}`).pathname
const healthPath = new URL('health', `http://localhost${basePath}`).pathname

export default defineConfig({
  base: basePath,
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',   // 允许局域网访问
    port: 3011,
    proxy: {
      // dev 时按部署前缀代理到 FastAPI
      [apiPath]: {
        target: proxyTarget,
        // SSE 端点需要禁用缓冲
        configure: (proxy) => {
          proxy.on('proxyReq', (_proxyReq, req) => {
            if (req.url?.includes('/stream')) {
              _proxyReq.setHeader('Accept', 'text/event-stream')
              _proxyReq.setHeader('Cache-Control', 'no-cache')
              _proxyReq.setHeader('Connection', 'keep-alive')
            }
          })
        },
      },
      [healthPath]: proxyTarget,
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
