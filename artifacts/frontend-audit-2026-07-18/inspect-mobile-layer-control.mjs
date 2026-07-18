import fs from 'node:fs/promises'
import playwright from '/home/jetson/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.js'

const { chromium } = playwright
const outputDir = process.env.BOTDOG_AUDIT_OUTPUT_DIR || '/home/jetson/Project/BOTDOG/BotDog/artifacts/frontend-audit-2026-07-18'
const storageState = process.env.BOTDOG_AUDIT_STORAGE_STATE || '/tmp/botdog-frontend-audit-storage.json'
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  storageState,
  viewport: { width: 390, height: 844 },
  locale: 'zh-CN',
})
const page = await context.newPage()
await page.goto('http://127.0.0.1:8000/nav-patrol.html', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(5_000)
const button = page.getByRole('button', { name: '点云图层' })
const before = await button.evaluate((element) => {
  const rect = element.getBoundingClientRect()
  const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
  return {
    buttonRect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
    viewport: { width: window.innerWidth, height: window.innerHeight },
    hitTag: hit?.tagName ?? null,
    hitClass: hit?.className ?? null,
    hitText: hit?.textContent?.trim().slice(0, 160) ?? null,
  }
})
await button.evaluate((element) => element.click())
await page.waitForTimeout(200)
const popover = page.locator('.pcd-layer-popover')
const popoverCount = await popover.count()
const after = popoverCount > 0
  ? await popover.evaluate((element) => {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      return {
        rect: { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom },
        display: style.display,
        visibility: style.visibility,
        clippedByViewport: rect.left < 0 || rect.top < 0 || rect.right > innerWidth || rect.bottom > innerHeight,
      }
    })
  : null
await fs.writeFile(
  `${outputDir}/mobile-layer-hit-test.json`,
  JSON.stringify({ before, popoverCount, after }, null, 2),
  'utf8',
)
await context.close()
await browser.close()
