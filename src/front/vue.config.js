const { defineConfig } = require('@vue/cli-service')

const backendPort = process.env.VUE_APP_BACKEND_PORT || '8010'
const httpTarget = `http://localhost:${backendPort}`
const wsTarget = `ws://localhost:${backendPort}`

module.exports = defineConfig({
  transpileDependencies: true,
  devServer: {
    proxy: {
      '/api': {
        target: httpTarget,
        changeOrigin: true
      },
      '/ws': {
        target: wsTarget,
        ws: true,
        changeOrigin: true
      }
    }
  }
})
