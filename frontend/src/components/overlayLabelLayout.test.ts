import { expect, it } from 'vitest';
import { placeOverlayLabel, type LabelRect } from './overlayLabelLayout';

it('keeps overlapping detection and pose labels inside their box and clear of the HUD', () => {
  const bounds = { x: 50, y: 50, width: 260, height: 220 };
  const occupied: LabelRect[] = [{ x: 0, y: 0, width: 150, height: 130 }];
  for (const text of ['person #1 · 测试人员 87%', '姿态待确认 #1', 'helmet 80%']) {
    const placed = placeOverlayLabel(text, bounds, occupied, s => s.length * 7)!;
    expect(placed).not.toBeNull();
    expect(placed.x).toBeGreaterThanOrEqual(bounds.x);
    expect(placed.y).toBeGreaterThanOrEqual(bounds.y);
    expect(placed.x + placed.width).toBeLessThanOrEqual(bounds.x + bounds.width);
    expect(placed.y + placed.height).toBeLessThanOrEqual(bounds.y + bounds.height);
    for (const r of occupied) {
      expect(placed.x >= r.x + r.width || placed.x + placed.width <= r.x
        || placed.y >= r.y + r.height || placed.y + placed.height <= r.y).toBe(true);
    }
    occupied.push(placed);
  }
});

it('wraps a long label in a narrow box without losing content', () => {
  const text = 'person #10 · 测试人员名字很长 95%';
  const placed = placeOverlayLabel(text, { x: 0, y: 0, width: 90, height: 180 }, [], s => s.length * 7)!;
  expect(placed.lines.length).toBeGreaterThan(1);
  expect(placed.lines.join('')).toBe(text);
  expect(placed.width).toBeLessThanOrEqual(82);
});
