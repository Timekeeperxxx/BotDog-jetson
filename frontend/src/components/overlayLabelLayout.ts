export type LabelRect = { x: number; y: number; width: number; height: number };

export function placeOverlayLabel(
  text: string,
  bounds: LabelRect,
  occupied: LabelRect[],
  measure: (text: string) => number,
): (LabelRect & { lines: string[] }) | null {
  const padding = 4;
  const lineHeight = 16;
  const maxWidth = bounds.width - padding * 2;
  if (maxWidth < 24 || bounds.height < lineHeight + padding * 2) return null;
  const lines: string[] = [];
  let line = '';
  for (const character of text) {
    if (line && measure(line + character) > maxWidth - 8) {
      lines.push(line);
      line = '';
    }
    line += character;
  }
  if (line) lines.push(line);
  const width = Math.min(maxWidth, Math.max(...lines.map(measure)) + 8);
  const height = lines.length * lineHeight + 4;
  const right = bounds.x + bounds.width - padding;
  const bottom = bounds.y + bounds.height - padding;
  // ponytail: greedy placement suits a handful of targets; dense scenes need grouped labels.
  const xs = [bounds.x + padding, right - width, ...occupied.map(r => r.x + r.width + padding)];
  const ys = [bounds.y + padding, ...occupied.map(r => r.y + r.height + padding)].sort((a, b) => a - b);
  for (const y of ys) {
    for (const x of xs) {
      if (x < bounds.x + padding || x + width > right || y < bounds.y + padding || y + height > bottom) continue;
      if (occupied.some(r => x < r.x + r.width + padding && x + width + padding > r.x
        && y < r.y + r.height + padding && y + height + padding > r.y)) continue;
      return { x, y, width, height, lines };
    }
  }
  return null;
}
