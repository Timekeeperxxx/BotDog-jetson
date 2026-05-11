import fs from 'node:fs'
import path from 'node:path'

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const frontendSrc = path.join(repoRoot, 'frontend', 'src')
const providerPath = path.join('frontend', 'src', 'runtime', 'EventStreamProvider.tsx')

const allowedProviderPatterns = [
  "new WebSocket(getWsUrl('/ws/event'))",
  'new WebSocket(getWsUrl("/ws/event"))',
  "/ws/event",
]

function walkFiles(dir, result = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (['node_modules', 'dist', 'build', 'coverage'].includes(entry.name)) {
        continue
      }
      walkFiles(path.join(dir, entry.name), result)
      continue
    }

    if (!/\.(ts|tsx|js|jsx)$/.test(entry.name)) {
      continue
    }
    result.push(path.join(dir, entry.name))
  }
  return result
}

function toPosix(relativePath) {
  return relativePath.split(path.sep).join('/')
}

const files = walkFiles(frontendSrc)
const violations = []
let providerSeen = false

for (const file of files) {
  const relativePath = toPosix(path.relative(repoRoot, file))
  const content = fs.readFileSync(file, 'utf8')
  const lines = content.split(/\r?\n/)

  if (relativePath === providerPath) {
    providerSeen = allowedProviderPatterns.some((pattern) => content.includes(pattern))
    continue
  }

  lines.forEach((line, index) => {
    const hasEventSocket = line.includes('new WebSocket') && line.includes('/ws/event')
    if (hasEventSocket) {
      violations.push(`${relativePath}: ${index + 1}: ${line.trim()}`)
    }
  })
}

if (!providerSeen) {
  console.warn('[check-event-stream-singleton] WARNING: EventStreamProvider.tsx did not match the expected /ws/event pattern.')
}

if (violations.length > 0) {
  console.error('[check-event-stream-singleton] ERROR: duplicate /ws/event WebSocket creation found:')
  for (const item of violations) {
    console.error(`- ${item}`)
  }
  process.exit(1)
}

console.log('[check-event-stream-singleton] OK: /ws/event is only created by EventStreamProvider.')
