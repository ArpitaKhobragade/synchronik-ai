import process from 'node:process'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  // A production bundle without the API URL would silently call http://127.0.0.1:8000 from users' browsers.
  if (command === 'build' && mode === 'production') {
    const api = env.VITE_API_BASE_URL || process.env.VITE_API_BASE_URL || ''
    if (!/^https?:\/\//.test(api) || /localhost|127\.0\.0\.1/.test(api)) {
      throw new Error(`VITE_API_BASE_URL must be set to the deployed backend URL for production builds (got "${api}").`)
    }
  }
  return { plugins: [react()] }
})
