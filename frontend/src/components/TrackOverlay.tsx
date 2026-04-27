import { useEffect, useRef, useCallback } from 'react';

export interface TrackOverlayData {
  persons: {
    bbox: number[]; // [x1, y1, x2, y2]
    conf: number;
    track_id?: number;
    is_stranger?: boolean;
  }[];
  active_bbox: number[] | null;
  zone_bbox?: number[] | null; // 防区 bounding box [x1,y1,x2,y2]
  zone_polygon?: number[][] | null; // 防区旋转四边形 [[x,y],[x,y],[x,y],[x,y]]
  tracker_bbox?: number[] | null;
  command: string | null;
  reason: string;
  state: string;
  frame_w: number;
  frame_h: number;
  deadband_px: number;
  anchor_y_stop_ratio: number;
  forward_area_ratio: number;
  zone_quality?: number;
  zone_lost?: boolean;
  foot_points?: Array<{ x: number; y: number; in_zone: boolean }>;
  intrusion_confirmed?: boolean;
  edge_margin_ratio?: number; // 边缘裕量比例，来自 GUARD_ZONE_EDGE_MARGIN_RATIO
}

interface Props {
  data: TrackOverlayData | null;
  videoRef: React.RefObject<HTMLVideoElement>;
}

export function TrackOverlay({ data, videoRef }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number>(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    const parent = canvas.parentElement;
    if (!parent) return;

    const rect = parent.getBoundingClientRect();
    const cw = rect.width;
    const ch = rect.height;
    if (cw < 10 || ch < 10) return;

    canvas.width = cw;
    canvas.height = ch;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, cw, ch);

    if (!data || data.frame_w <= 0 || data.frame_h <= 0) return;

    // 与主视频 object-cover 保持一致：
    // 先等比放大，再居中裁切
    const scale = Math.max(cw / data.frame_w, ch / data.frame_h);
    const drawW = data.frame_w * scale;
    const drawH = data.frame_h * scale;
    const offsetX = (cw - drawW) / 2;
    const offsetY = (ch - drawH) / 2;

    const mapX = (x: number) => offsetX + x * scale;
    const mapY = (y: number) => offsetY + y * scale;

    const mapRect = (bbox: number[]) => {
      const [x1, y1, x2, y2] = bbox;
      return {
        rx: mapX(x1),
        ry: mapY(y1),
        rw: (x2 - x1) * scale,
        rh: (y2 - y1) * scale,
        x1,
        y1,
        x2,
        y2,
      };
    };

    // ─── 1. 水平死区（两条蓝色虚线） ───────────────────────────────
    const centerX = cw / 2;
    const dbPx = data.deadband_px * scale;

    ctx.save();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = 'rgba(80,160,255,0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(centerX - dbPx, 0);
    ctx.lineTo(centerX - dbPx, ch);
    ctx.moveTo(centerX + dbPx, 0);
    ctx.lineTo(centerX + dbPx, ch);
    ctx.stroke();
    ctx.restore();

    ctx.save();
    ctx.fillStyle = 'rgba(80,160,255,0.35)';
    ctx.font = '10px monospace';
    ctx.fillText('← 死区 →', centerX - 22, 14);
    ctx.restore();

    // ─── 2. 纵向停止线（黄色虚线） ──────────────────────────────────
    const stopY = offsetY + data.anchor_y_stop_ratio * data.frame_h * scale;

    ctx.save();
    ctx.setLineDash([8, 4]);
    ctx.strokeStyle = 'rgba(255,200,0,0.55)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, stopY);
    ctx.lineTo(cw, stopY);
    ctx.stroke();

    ctx.fillStyle = 'rgba(255,200,0,0.55)';
    ctx.font = '10px monospace';
    ctx.fillText(`停止线 y=${Math.round(stopY)}`, 6, stopY - 4);
    ctx.restore();

    // ─── 3. 所有检测到的 person ─────────────────────────────
    for (const p of data.persons) {
      if (!Array.isArray(p.bbox) || p.bbox.length !== 4) continue;

      const { rx, ry, rw, rh, y2 } = mapRect(p.bbox);
      const bottomY = mapY(y2);

      const isKnown = p.is_stranger === false;
      const boxColor = isKnown ? 'rgba(0,220,120,0.8)' : 'rgba(255,100,0,0.8)';
      const labelColor = isKnown ? 'rgba(0,100,50,0.8)' : 'rgba(150,40,0,0.8)';

      ctx.save();

      ctx.strokeStyle = boxColor;
      ctx.lineWidth = 1.5;
      ctx.strokeRect(rx, ry, rw, rh);

      const headerText = `ID:${p.track_id !== undefined ? p.track_id : '?'} | ${(p.conf * 100).toFixed(0)}%`;
      ctx.fillStyle = labelColor;
      ctx.fillRect(rx, ry - 14, 88, 14);
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 10px monospace';
      ctx.fillText(headerText, rx + 4, ry - 3);

      if (p.is_stranger !== undefined) {
        const tagText = p.is_stranger ? 'STRANGER' : 'KNOWN';
        const w = ctx.measureText(tagText).width + 8;
        ctx.fillStyle = p.is_stranger
          ? 'rgba(220,0,0,0.85)'
          : 'rgba(0,180,80,0.85)';
        ctx.fillRect(rx, bottomY, w, 14);
        ctx.fillStyle = '#fff';
        ctx.fillText(tagText, rx + 4, bottomY + 10);
      }

      ctx.restore();
    }

    // ─── 3.5. 人的脚点记录 ──────────────────────────────────────
    if (data.foot_points && data.foot_points.length > 0) {
      for (const fp of data.foot_points) {
        const fx = mapX(fp.x);
        const fy = mapY(fp.y);

        ctx.save();
        ctx.beginPath();
        ctx.arc(fx, fy, 4, 0, Math.PI * 2);
        ctx.fillStyle = fp.in_zone
          ? 'rgba(255,50,50,0.9)'
          : 'rgba(0,220,120,0.7)';
        ctx.fill();

        ctx.strokeStyle = 'rgba(0,0,0,0.8)';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.fillStyle = fp.in_zone ? '#ff3232' : '#00dc78';
        ctx.font = 'bold 9px monospace';
        ctx.fillText('FOOT', fx + 6, fy + 3);
        ctx.restore();
      }
    }

    // ─── 3.8. 边缘裕量保护区 ───────────────────────────────
    if (data.edge_margin_ratio && data.edge_margin_ratio > 0) {
      const mx = cw * data.edge_margin_ratio;
      const my = ch * data.edge_margin_ratio;
      const dangerColor = 'rgba(255, 60, 60, 0.13)';
      const borderColor = 'rgba(255, 100, 80, 0.7)';

      ctx.save();

      ctx.fillStyle = dangerColor;
      ctx.fillRect(0, 0, mx, ch);           // 左
      ctx.fillRect(cw - mx, 0, mx, ch);     // 右
      ctx.fillRect(0, ch - my, cw, my);     // 下

      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(mx, 0);
      ctx.lineTo(mx, ch - my);
      ctx.moveTo(cw - mx, 0);
      ctx.lineTo(cw - mx, ch - my);
      ctx.moveTo(mx, ch - my);
      ctx.lineTo(cw - mx, ch - my);
      ctx.stroke();

      ctx.setLineDash([]);
      ctx.fillStyle = borderColor;
      ctx.font = '9px monospace';
      ctx.fillText(`安全边界 ${Math.round(data.edge_margin_ratio * 100)}%`, mx + 4, ch - my - 4);

      ctx.restore();
    }

    // ─── 4. 防区多边形 / 防区框 ─────────────────────────────
    if (data.zone_polygon && data.zone_polygon.length >= 3) {
      const pts = data.zone_polygon.map(([px, py]) => [mapX(px), mapY(py)]);

      ctx.save();
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(pts[i][0], pts[i][1]);
      }
      ctx.closePath();

      ctx.fillStyle = 'rgba(255, 220, 0, 0.18)';
      ctx.fill();

      ctx.setLineDash([6, 3]);
      ctx.strokeStyle = 'rgba(255, 220, 0, 0.95)';
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = 'rgba(255,220,0,0.95)';
      ctx.font = 'bold 11px monospace';
      ctx.fillText('防区(颜色检测)', pts[0][0] + 3, pts[0][1] - 5);

      ctx.restore();
    } else if (data.zone_bbox) {
      const { rx, ry, rw, rh } = mapRect(data.zone_bbox);

      ctx.save();
      ctx.setLineDash([6, 3]);
      ctx.strokeStyle = 'rgba(255, 220, 0, 0.9)';
      ctx.lineWidth = 2;
      ctx.strokeRect(rx, ry, rw, rh);

      ctx.fillStyle = 'rgba(255, 220, 0, 0.12)';
      ctx.fillRect(rx, ry, rw, rh);

      ctx.fillStyle = 'rgba(255,220,0,0.95)';
      ctx.font = 'bold 11px monospace';
      ctx.fillText('防区', rx + 3, ry - 5);

      ctx.restore();
    }

    // ─── 5. 锁定目标（红色加粗框） ─────────────────────────
    if (data.active_bbox) {
      const [x1, , x2, y2] = data.active_bbox;
      const { rx, ry, rw, rh } = mapRect(data.active_bbox);

      ctx.save();
      ctx.strokeStyle = 'rgba(255,60,60,0.85)';
      ctx.lineWidth = 2.5;
      ctx.strokeRect(rx, ry, rw, rh);

      const stateBadge =
        data.state && data.state !== 'IDLE' ? data.state : 'TRACKING';

      ctx.font = 'bold 11px monospace';
      const badgeW = Math.max(ctx.measureText(stateBadge).width + 16, 80);

      ctx.fillStyle = 'rgba(255,40,40,0.9)';
      ctx.fillRect(rx, ry - 18, badgeW, 18);

      ctx.fillStyle = '#fff';
      ctx.fillText(` ${stateBadge}`, rx + 4, ry - 5);

      const anchorX = mapX((x1 + x2) / 2);
      const anchorY = mapY(y2);

      ctx.beginPath();
      ctx.arc(anchorX, anchorY, 4, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,100,0,0.9)';
      ctx.fill();

      ctx.restore();
    }

    // ─── 6. 决策信息（左下角） ─────────────────────────────
    if (data.command || data.state) {
      const cmdLabel: Record<string, string> = {
        forward: '↑ 前进',
        left: '← 左转',
        right: '→ 右转',
        stop: '■ 停止',
      };

      const cmdText = data.command ? (cmdLabel[data.command] || data.command) : '';
      const stateText = data.state || '';

      ctx.save();

      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.fillRect(4, ch - 52, 320, 48);

      ctx.fillStyle = '#aaa';
      ctx.font = '10px monospace';
      ctx.fillText(`状态: ${stateText} | 人数: ${data.persons.length}`, 10, ch - 36);

      if (cmdText) {
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 13px monospace';
        ctx.fillText(cmdText, 10, ch - 20);
      }

      if (data.reason) {
        ctx.fillStyle = '#8cf';
        ctx.font = '10px monospace';
        ctx.fillText(data.reason.slice(0, 45), 90, ch - 20);
      }

      ctx.restore();
    }
  }, [data, videoRef]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const handler = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(draw);
    };

    window.addEventListener('resize', handler);
    return () => {
      window.removeEventListener('resize', handler);
      cancelAnimationFrame(rafRef.current);
    };
  }, [draw]);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 pointer-events-none z-20"
    />
  );
}
