import fs from 'node:fs/promises'
import playwright from '/home/jetson/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.js'

const { chromium } = playwright
const outputDir = process.env.BOTDOG_AUDIT_OUTPUT_DIR || '/home/jetson/Project/BOTDOG/BotDog/artifacts/frontend-audit-2026-07-18'
const storageState = process.env.BOTDOG_AUDIT_STORAGE_STATE || '/tmp/botdog-frontend-audit-storage.json'
const baseUrl = 'http://127.0.0.1:8000'
const axeUrl = 'https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.10.3/axe.min.js'
const browser = await chromium.launch({ headless: true })

async function audit(name, path, viewport, authenticated = true) {
  const context = await browser.newContext({
    ...(authenticated ? { storageState } : {}),
    viewport,
    locale: 'zh-CN',
    colorScheme: 'dark',
  })
  const page = await context.newPage()
  await page.goto(`${baseUrl}${path}`, { waitUntil: 'domcontentloaded', timeout: 30_000 })
  await page.waitForTimeout(4_000)
  await page.addScriptTag({ url: axeUrl })
  const result = await page.evaluate(async () => {
    const report = await window.axe.run(document, {
      resultTypes: ['violations'],
    })
    return report.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      help: violation.help,
      helpUrl: violation.helpUrl,
      nodes: violation.nodes.map((node) => ({
        target: node.target,
        html: node.html.slice(0, 500),
        failureSummary: node.failureSummary,
      })),
    }))
  })
  await context.close()
  return { name, path, viewport, violations: result }
}

const results = [
  await audit('login-desktop', '/login', { width: 1440, height: 900 }, false),
  await audit('console-desktop', '/', { width: 1440, height: 900 }),
  await audit('navigation-desktop', '/nav-patrol.html', { width: 1440, height: 900 }),
  await audit('admin-desktop', '/admin', { width: 1440, height: 900 }),
  await audit('navigation-mobile', '/nav-patrol.html', { width: 390, height: 844 }),
]

await fs.writeFile(`${outputDir}/axe-results.json`, JSON.stringify(results, null, 2), 'utf8')
await browser.close()
