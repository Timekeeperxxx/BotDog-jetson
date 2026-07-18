import playwright from '/home/jetson/.npm/_npx/e41f203b7505f1fb/node_modules/playwright/index.js'

const username = process.env.AUTH_ADMIN_USERNAME
const password = process.env.AUTH_ADMIN_PASSWORD
if (!username || !password) throw new Error('缺少审计登录环境变量')

const { chromium } = playwright
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ locale: 'zh-CN' })
const page = await context.newPage()
await page.goto('http://127.0.0.1:8000/login', { waitUntil: 'domcontentloaded' })
await page.getByRole('textbox', { name: '用户名' }).fill(username)
await page.getByLabel('密码').fill(password)
await page.getByRole('button', { name: '登录' }).click()
await page.waitForURL((url) => url.pathname !== '/login', { timeout: 15_000 })
await context.storageState({ path: '/tmp/botdog-frontend-audit-storage.json' })
await browser.close()
