import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ command }) => ({
  // GitHub Pages serves this project from /Out-Brake-Overtake/ rather than
  // the domain root. Keep local development at / for convenience.
  base: command === 'build' ? '/Out-Brake-Overtake/' : '/',
  plugins: [react()],
}))
