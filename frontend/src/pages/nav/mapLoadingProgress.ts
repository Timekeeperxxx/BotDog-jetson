export type MapLoadingDetail = {
  label: string
  filename: string | null
  completed: number | null
  total: number | null
  detail: string | null
}

// Only the two count messages emitted by pcd_potree.py are determinate.
// Counts describe one file, never the entire scene or subsequent download.
export function parseMapLoadingDetail(message: string): MapLoadingDetail {
  const fallback: MapLoadingDetail = {
    label: '准备地图', filename: null, completed: null, total: null,
    detail: message.trim() || '正在获取地图数据',
  }
  const count = '(?:\\d{1,3}(?:,\\d{3})+|\\d+)'
  const match = message.trim().match(new RegExp(
    `^(读取|整理) (.+)[：:]\\s*(${count})(?:\\s*/\\s*(${count}))?\\s*点$`,
  ))
  if (!match) return fallback
  const completed = Number(match[3].replaceAll(',', ''))
  const total = match[4] ? Number(match[4].replaceAll(',', '')) : null
  if (!Number.isSafeInteger(completed) || completed < 0
      || (total !== null && (!Number.isSafeInteger(total) || total <= 0 || completed > total))) {
    return fallback
  }
  // Reading has no known total. Do not infer one from any other file or stage.
  if (match[1] === '读取' && total !== null) return fallback
  return {
    label: match[1] === '读取' ? '读取点云' : '整理点云',
    filename: match[2], completed, total, detail: null,
  }
}

export function formatPointCount(value: number): string {
  return value.toLocaleString('en-US')
}
