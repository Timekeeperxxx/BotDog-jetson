import fs from 'node:fs/promises'
import playwright from '/home/jetson/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.js'

const { chromium } = playwright

const outputDir = process.env.BOTDOG_AUDIT_OUTPUT_DIR || '/home/jetson/Project/BOTDOG/BotDog/artifacts/frontend-audit-2026-07-18'
const storageState = process.env.BOTDOG_AUDIT_STORAGE_STATE || '/tmp/botdog-frontend-audit-storage.json'
const baseUrl = 'http://127.0.0.1:8000'
const browser = await chromium.launch({ headless: true })
const diagnostics = []

async function capture({ name, path, viewport, waitMs = 5000 }) {
  const context = await browser.newContext({
    storageState,
    viewport,
    locale: 'zh-CN',
    colorScheme: 'dark',
  })
  const page = await context.newPage()
  const entry = { name, path, viewport, console: [], pageErrors: [], failedRequests: [], badResponses: [] }
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      entry.console.push({ type: message.type(), text: message.text() })
    }
  })
  page.on('pageerror', (error) => entry.pageErrors.push(error.message))
  page.on('requestfailed', (request) => {
    entry.failedRequests.push({ url: request.url(), error: request.failure()?.errorText ?? 'unknown' })
  })
  page.on('response', (response) => {
    if (response.status() >= 400) entry.badResponses.push({ url: response.url(), status: response.status() })
  })

  await page.goto(`${baseUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.waitForTimeout(waitMs)
  entry.url = page.url()
  entry.title = await page.title()
  entry.bodyText = (await page.locator('body').innerText()).slice(0, 12_000)
  await fs.writeFile(`${outputDir}/${name}.aria.yml`, await page.locator('body').ariaSnapshot(), 'utf8')
  await page.screenshot({ path: `${outputDir}/${name}.png`, fullPage: false })
  diagnostics.push(entry)
  await context.close()
}

await capture({ name: '03-console-desktop', path: '/', viewport: { width: 1440, height: 900 } })
await capture({ name: '04-navigation-desktop', path: '/nav-patrol.html', viewport: { width: 1440, height: 900 }, waitMs: 10_000 })
await capture({ name: '05-admin-desktop', path: '/admin', viewport: { width: 1440, height: 900 } })
await capture({ name: '06-navigation-mobile', path: '/nav-patrol.html', viewport: { width: 390, height: 844 }, waitMs: 7_000 })
await fs.writeFile(`${outputDir}/browser-diagnostics.json`, JSON.stringify(diagnostics, null, 2), 'utf8')
await browser.close()
