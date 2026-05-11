import fs from 'node:fs'
import path from 'node:path'

const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const frontendSrc = path.join(repoRoot, 'frontend', 'src')
const providerPath = path.join('frontend', 'src', 'runtime', 'EventStreamProvider.tsx')

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
    providerSeen = content.includes("new WebSocket") && content.includes('/ws/event')
    continue
  }

  if (!content.includes('new WebSocket') || !content.includes('/ws/event')) {
    continue
  }

  const newWebSocketLines = []
  const eventUrlLines = []

  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (line.includes('new WebSocket')) {
      newWebSocketLines.push(`  line ${index + 1}: ${trimmed}`)
    }
    if (line.includes('/ws/event')) {
      eventUrlLines.push(`  line ${index + 1}: ${trimmed}`)
    }
  })

  violations.push([
    `- ${relativePath}`,
    ...newWebSocketLines.slice(0, 3),
    ...eventUrlLines.slice(0, 3),
  ].join('\n'))
}

if (!providerSeen) {
  console.warn('[check-event-stream-singleton] WARNING: EventStreamProvider.tsx did not match the expected /ws/event pattern.')
}

if (violations.length > 0) {
  console.error('[check-event-stream-singleton] ERROR: duplicate /ws/event WebSocket creation found:')
  for (const item of violations) {
    console.error(item)
  }
  process.exit(1)
}

console.log('[check-event-stream-singleton] OK: /ws/event is only created by EventStreamProvider.')
