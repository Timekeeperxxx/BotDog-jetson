#!/usr/bin/env node

import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const require = createRequire(import.meta.url)
const playwrightModule = process.env.PLAYWRIGHT_MODULE || '/tmp/botdog-playwright/node_modules/playwright'
const { chromium } = require(playwrightModule)

const baseUrl = process.env.FACE_UI_BASE_URL || 'http://127.0.0.1:4173'
const outputDir = resolve(process.argv[2] || 'artifacts/face-recognition-validation')
await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 })

await page.addInitScript(() => {
  localStorage.setItem('botdog-auth', JSON.stringify({
    accessToken: 'acceptance-token', id: 1, username: 'admin', role: 'admin', must_change_password: false,
  }))
})

await page.route('**/api/v1/**', async (route) => {
  const path = new URL(route.request().url()).pathname
  let body = {}
  if (path === '/api/v1/auth/me') {
    body = { id: 1, username: 'admin', role: 'admin', must_change_password: false }
  } else if (path === '/api/v1/face-identities') {
    body = [{
      id: 1,
      display_name: '测试人员A',
      notes: '合成验收人员',
      enabled: true,
      created_at: '2026-08-04T12:00:00.000Z',
      updated_at: '2026-08-04T12:00:00.000Z',
      templates: [{
        id: 1, identity_id: 1, dimension: 128, model_name: 'OpenCV SFace',
        model_version: '2021dec', quality: 0.8319, created_at: '2026-08-04T12:00:00.000Z',
      }],
    }]
  } else if (path === '/api/v1/face-recognition/status') {
    body = {
      enabled: true, available: true, engine_loaded: true, model_name: 'OpenCV SFace',
      detect_model_path: '/home/jetson/Projects/Models/face_detection_yunet_2023mar.onnx',
      recognition_model_path: '/home/jetson/Projects/Models/face_recognition_sface_2021dec.onnx',
      identity_count: 1, template_count: 1, match_threshold: 0.45,
      last_reload_at: '2026-08-04T12:00:00.000Z', error: null,
    }
  } else if (path === '/api/v1/system/health') {
    body = { status: 'healthy', mavlink_connected: true, uptime: 120 }
  } else if (path === '/api/v1/system-info') {
    body = { groups: [] }
  } else if (path === '/api/v1/system/resources') {
    body = {
      collected_at: '2026-08-04T12:00:00.000Z', hostname: 'jetson', platform: 'Linux',
      architecture: 'aarch64', cpu_count: 8, load_average: [0.2, 0.3, 0.4], host_uptime_seconds: 3600,
      memory: { total_bytes: 17179869184, used_bytes: 4294967296, available_bytes: 12884901888, usage_percent: 25, swap_total_bytes: 0, swap_used_bytes: 0 },
      disk: { path: '/', total_bytes: 128849018880, used_bytes: 42949672960, free_bytes: 85899345920, usage_percent: 33.3 },
    }
  } else if (path === '/api/v1/logs' || path === '/api/v1/evidence') {
    body = { items: [] }
  } else if (path === '/api/v1/config') {
    body = { configs: {} }
  } else if (path === '/api/v1/video-sources') {
    body = { sources: [] }
  } else if (path === '/api/v1/network-interfaces') {
    body = { interfaces: [] }
  } else if (path.includes('/pcd-scenes')) {
    body = { root: '', items: [] }
  } else if (path.includes('/nav/tasks')) {
    body = { items: [] }
  }
  await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
})

const pageErrors = []
const consoleErrors = []
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
await page.goto(`${baseUrl}/admin`, { waitUntil: 'networkidle' })
const menuItem = page.getByRole('button', { name: '人员识别库', exact: true })
if (await menuItem.count() === 0) {
  await page.screenshot({ path: resolve(outputDir, 'admin-face-identities-debug.png'), fullPage: true })
  throw new Error(`未找到人员识别库菜单，页面错误: ${pageErrors.join('; ')}；控制台: ${consoleErrors.join('; ')}；页面文本: ${(await page.locator('body').innerText()).slice(0, 1200)}`)
}
await menuItem.click()
await page.getByText('测试人员A').waitFor()
await page.screenshot({ path: resolve(outputDir, 'admin-face-identities.png'), fullPage: true })

if (pageErrors.length) {
  throw new Error(`页面运行错误: ${pageErrors.join('; ')}`)
}
console.log(JSON.stringify({
  screenshot: resolve(outputDir, 'admin-face-identities.png'),
  title: await page.title(),
  identityVisible: await page.getByText('测试人员A').isVisible(),
  statusVisible: await page.getByText('0.45').isVisible(),
}, null, 2))

await browser.close()
