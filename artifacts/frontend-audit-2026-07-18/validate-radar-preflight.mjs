import fs from 'node:fs/promises'
import playwright from '/home/jetson/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.js'

const { chromium } = playwright
const outputDir = process.env.BOTDOG_AUDIT_OUTPUT_DIR || '/home/jetson/Project/BOTDOG/BotDog/artifacts/frontend-fix-validation-2026-07-18'
const storageState = process.env.BOTDOG_AUDIT_STORAGE_STATE || '/tmp/botdog-frontend-audit-storage.json'
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  storageState,
  viewport: { width: 1440, height: 900 },
  locale: 'zh-CN',
})
const page = await context.newPage()
let mappingStartRequests = 0

await page.route('**/api/v1/nav/mapping/set-enabled', async (route) => {
  mappingStartRequests += 1
  await route.fulfill({
    status: 503,
    contentType: 'application/json',
    body: JSON.stringify({ detail: '浏览器验证已安全拦截建图请求' }),
  })
})

await page.goto('http://127.0.0.1:8000/nav-patrol.html', {
  waitUntil: 'domcontentloaded',
  timeout: 30_000,
})
await page.waitForTimeout(3_000)
await page.getByRole('button', { name: '开始建图' }).click()
await page.getByRole('textbox', { name: '场景名称' }).fill('雷达预检验证')
const startedAt = performance.now()
await page.getByRole('button', { name: '已保持静止，开始建图' }).click()
const alert = page.getByRole('alert')
await alert.waitFor({ state: 'visible', timeout: 8_000 })
const elapsedMs = Math.round(performance.now() - startedAt)
const alertText = (await alert.innerText()).trim()
await page.screenshot({ path: `${outputDir}/10-radar-preflight-alert.png`, fullPage: false })
await fs.writeFile(
  `${outputDir}/radar-preflight-e2e.json`,
  JSON.stringify({ elapsedMs, alertText, mappingStartRequests }, null, 2),
  'utf8',
)

await context.close()
await browser.close()
