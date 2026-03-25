/**
 * useTrackOverlay — 在视频画布上绘制 YOLO 检测框和死区辅助线。
 *
 * 绘制内容：
 * - 所有检测到的人物框（青色虚线）+ 置信度标签
 * - 锁定目标的框（亮绿色实线）
 * - 水平方向死区（中心垂直带，左右各 deadband_px）
 * - 纵向停止线（anchor_y_stop_ratio 位置的水平虚线，不准前进线）
 */

import { useEffect } from 'react';
import type { TrackDetection } from './useEventWebSocket';

interface Options {
  /** 是否显示叠层（例如只在跟踪启用时显示） */
  enabled?: boolean;
}

export function useTrackOverlay(
  canvasRef: React.RefObject<HTMLCanvasElement | null>,
  detection: TrackDetection | null,
  options: Options = {},
) {
  const { enabled = true } = options;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Clear previous frame
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!enabled || !detection) return;

    const { persons, active_bbox, frame_w, frame_h, deadband_px, anchor_y_stop_ratio } = detection;

    const cw = canvas.width;
    const ch = canvas.height;

    // Scale factors: AI frame → canvas display size
    const sx = cw / frame_w;
    const sy = ch / frame_h;

    const scale = (x: number, y: number) => [x * sx, y * sy] as const;

    // ── 1. Deadband vertical zone (center ± deadband_px) ──────────────────
    const centerX = frame_w / 2;
    const [leftX] = scale(centerX - deadband_px, 0);
    const [rightX] = scale(centerX + deadband_px, 0);

    ctx.save();
    // Semi-transparent fill
    ctx.fillStyle = 'rgba(255, 230, 0, 0.07)';
    ctx.fillRect(leftX, 0, rightX - leftX, ch);
    // Dashed vertical borders
    ctx.strokeStyle = 'rgba(255, 230, 0, 0.5)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(leftX, 0); ctx.lineTo(leftX, ch);
    ctx.moveTo(rightX, 0); ctx.lineTo(rightX, ch);
    ctx.stroke();
    // Label
    ctx.setLineDash([]);
    ctx.font = '10px monospace';
    ctx.fillStyle = 'rgba(255, 230, 0, 0.7)';
    ctx.fillText(`◄ ${deadband_px}px ►`, leftX + 4, 14);
    ctx.restore();

    // ── 2. Anchor Y stop line ─────────────────────────────────────────────
    const stopY = anchor_y_stop_ratio * ch;
    ctx.save();
    ctx.strokeStyle = 'rgba(255, 80, 80, 0.7)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([8, 5]);
    ctx.beginPath();
    ctx.moveTo(0, stopY); ctx.lineTo(cw, stopY);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.font = '10px monospace';
    ctx.fillStyle = 'rgba(255, 80, 80, 0.85)';
    ctx.fillText(`⛔ 停止线 ${Math.round(anchor_y_stop_ratio * 100)}%`, 6, stopY - 4);
    ctx.restore();

    // ── 3. All persons (cyan dashed boxes) ────────────────────────────────
    for (const p of persons) {
      const [x1r, y1r] = scale(p.bbox[0], p.bbox[1]);
      const [x2r, y2r] = scale(p.bbox[2], p.bbox[3]);
      ctx.save();
      ctx.strokeStyle = 'rgba(0, 220, 255, 0.75)';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 3]);
      ctx.strokeRect(x1r, y1r, x2r - x1r, y2r - y1r);
      ctx.setLineDash([]);
      ctx.font = 'bold 10px monospace';
      ctx.fillStyle = 'rgba(0, 220, 255, 0.9)';
      ctx.fillText(`${Math.round(p.conf * 100)}%`, x1r + 3, y1r + 11);
      ctx.restore();
    }

    // ── 4. Locked target (bright green solid box) ─────────────────────────
    if (active_bbox) {
      const [ax1, ay1] = scale(active_bbox[0], active_bbox[1]);
      const [ax2, ay2] = scale(active_bbox[2], active_bbox[3]);
      ctx.save();
      ctx.strokeStyle = '#00ff88';
      ctx.lineWidth = 2.5;
      ctx.setLineDash([]);
      ctx.strokeRect(ax1, ay1, ax2 - ax1, ay2 - ay1);
      // Top label bar
      ctx.fillStyle = '#00ff88';
      ctx.fillRect(ax1, ay1 - 16, 60, 16);
      ctx.fillStyle = '#000';
      ctx.font = 'bold 10px monospace';
      ctx.fillText('🎯 目标', ax1 + 3, ay1 - 4);
      // Anchor dot (bottom center)
      const anchorX = (ax1 + ax2) / 2;
      ctx.beginPath();
      ctx.arc(anchorX, ay2, 4, 0, Math.PI * 2);
      ctx.fillStyle = '#00ff88';
      ctx.fill();
      ctx.restore();
    }
  }, [canvasRef, detection, enabled]);

  return null;
}
