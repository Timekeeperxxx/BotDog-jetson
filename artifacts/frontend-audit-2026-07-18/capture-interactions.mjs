import fs from 'node:fs/promises'
import playwright from '/home/jetson/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.js'

const { chromium } = playwright
const outputDir = process.env.BOTDOG_AUDIT_OUTPUT_DIR || '/home/jetson/Project/BOTDOG/BotDog/artifacts/frontend-audit-2026-07-18'
const storageState = process.env.BOTDOG_AUDIT_STORAGE_STATE || '/tmp/botdog-frontend-audit-storage.json'
const baseUrl = 'http://127.0.0.1:8000'
const browser = await chromium.launch({ headless: true })

async function openPage(path, viewport) {
  const context = await browser.newContext({ storageState, viewport, locale: 'zh-CN', colorScheme: 'dark' })
  const page = await context.newPage()
  await page.goto(`${baseUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.waitForTimeout(5_000)
  return { context, page }
}

async function save(page, name) {
  await fs.writeFile(`${outputDir}/${name}.aria.yml`, await page.locator('body').ariaSnapshot(), 'utf8')
  await page.screenshot({ path: `${outputDir}/${name}.png`, fullPage: false })
}

{
  const { context, page } = await openPage('/nav-patrol.html', { width: 1440, height: 900 })
  await page.getByRole('button', { name: '点云图层' }).click({ force: true })
  await page.waitForTimeout(500)
  await save(page, '07-point-cloud-layers-desktop')
  await context.close()
}

{
  const { context, page } = await openPage('/nav-patrol.html', { width: 390, height: 844 })
  await page.getByRole('button', { name: '点云图层' }).click({ force: true })
  await page.waitForTimeout(500)
  await save(page, '08-point-cloud-layers-mobile')
  await context.close()
}

{
  const { context, page } = await openPage('/admin', { width: 1440, height: 900 })
  const firstExecute = page.getByRole('button', { name: '执行重启后端' })
  await firstExecute.scrollIntoViewIfNeeded()
  await firstExecute.click()
  await page.waitForTimeout(400)
  await save(page, '09-admin-danger-confirmation')
  await context.close()
}

await browser.close()
