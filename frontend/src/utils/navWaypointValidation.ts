export type WaypointNameValidationResult =
  | { ok: true; value: string }
  | { ok: false; message: string }

export function validateWaypointName(
  rawValue: string,
  existingNames: string[],
): WaypointNameValidationResult {
  const name = rawValue.trim()
  if (!name) {
    return { ok: false, message: '请输入导航点名称' }
  }

  if (existingNames.some((item) => item.trim() === name)) {
    return { ok: false, message: '导航点名称不能重复' }
  }

  return { ok: true, value: name }
}
