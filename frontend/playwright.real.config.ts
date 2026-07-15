import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'critical-real-stack.spec.ts',
  timeout: 90_000,
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium-real-stack', use: { ...devices['Desktop Chrome'] } }],
})
