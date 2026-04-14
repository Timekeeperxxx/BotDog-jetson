/**
 * ZoneDrawer — 禁区绘制工具叠层。
 *
 * 叠加在视频画面上方的透明 canvas，支持：
 * - 点击画面逐点添加多边形顶点
 * - 实时预览当前正在绘制的多边形（绿色）
 * - 已保存的区域绘制为半透明红色覆盖层
 * - 右键或按 ESC 取消当前绘制
 * - 点击"保存"将区域存入后端，并同步到 ZoneService
 * - 点击"清除"删除所有已保存区域（逐一 DELETE）
 *
 * 坐标系：后端使用原始像素坐标（frame_w × frame_h），
 * 本组件在存储前将点坐标从 canvas 百分比换算到后端像素坐标。
 */

import React, { useRef, useEffect, useState, useCallback } from 'react';
import { getApiUrl } from '../config/api';

interface Point {
  x: number; // canvas 内 [0,1] 归一化坐标
  y: number;
}

interface SavedZone {
  zone_id: number;
  zone_name: string;
  polygon_json: string; // "[[x,y],...]" 像素坐标
  enabled: boolean;
}

interface Props {
  frameW: number; // AI 原始画面宽（像素），用于坐标转换
  frameH: number; // AI 原始画面高（像素）
  active: boolean; // 是否处于绘制模式
  onClose: () => void; // 关闭绘制模式
}

export const ZoneDrawer: React.FC<Props> = ({ frameW, frameH, active, onClose }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [points, setPoints] = useState<Point[]>([]); // 当前正在绘的点（归一化）
  const [savedZones, setSavedZones] = useState<SavedZone[]>([]);
  const [saving, setSaving] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  // ── 加载已有区域 ────────────────────────────────────────────
  const fetchZones = useCallback(async () => {
    try {
      const res = await fetch(getApiUrl('/api/v1/focus-zones'));
      if (!res.ok) return;
      const data: SavedZone[] = await res.json();
      setSavedZones(data);
    } catch (_) {}
  }, []);

  useEffect(() => { void fetchZones(); }, [fetchZones]);

  // ── 绘制 canvas ─────────────────────────────────────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const parent = canvas.parentElement;
    if (!parent) return;
    const rect = parent.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;
    const cw = rect.width;
    const ch = rect.height;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, cw, ch);

    // —— 已保存区域（红色半透明）
    for (const zone of savedZones) {
      if (!zone.enabled) continue;
      try {
        const pts: number[][] = JSON.parse(zone.polygon_json);
        if (pts.length < 3) continue;
        const fw = frameW || cw;
        const fh = frameH || ch;
        ctx.save();
        ctx.beginPath();
        pts.forEach(([px, py], i) => {
          const cx2 = (px / fw) * cw;
          const cy2 = (py / fh) * ch;
          if (i === 0) ctx.moveTo(cx2, cy2); else ctx.lineTo(cx2, cy2);
        });
        ctx.closePath();
        ctx.fillStyle = 'rgba(220,40,40,0.18)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,60,60,0.75)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
        // 区域名称
        ctx.fillStyle = 'rgba(255,100,100,0.9)';
        ctx.font = 'bold 11px monospace';
        const cx2 = (pts[0][0] / fw) * cw;
        const cy2 = (pts[0][1] / fh) * ch;
        ctx.fillText(`⬡ ${zone.zone_name}`, cx2 + 4, cy2 - 4);
        ctx.restore();
      } catch (_) {}
    }

    if (!active) return;

    // —— 当前绘制中的多边形（绿色）
    if (points.length === 0) return;
    ctx.save();
    ctx.beginPath();
    points.forEach((pt, i) => {
      if (i === 0) ctx.moveTo(pt.x * cw, pt.y * ch);
      else ctx.lineTo(pt.x * cw, pt.y * ch);
    });
    ctx.strokeStyle = 'rgba(0,255,120,0.85)';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 4]);
    ctx.stroke();

    // 顶点圆点
    for (const pt of points) {
      ctx.beginPath();
      ctx.arc(pt.x * cw, pt.y * ch, 4, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0,255,120,0.9)';
      ctx.fill();
    }
    ctx.restore();
  }, [points, savedZones, active, frameW, frameH]);

  useEffect(() => { draw(); }, [draw]);

  // resize 监听
  useEffect(() => {
    const handler = () => draw();
    window.addEventListener('resize', handler);
    return () => window.removeEventListener('resize', handler);
  }, [draw]);

  // ── 鼠标点击添加点 ──────────────────────────────────────────
  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!active) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const nx = (e.clientX - rect.left) / rect.width;
    const ny = (e.clientY - rect.top) / rect.height;
    setPoints(prev => [...prev, { x: nx, y: ny }]);
  }, [active]);

  // ESC 取消
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setPoints([]); onClose(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // ── 保存 ───────────────────────────────────────────────────
  const save = async () => {
    if (points.length < 3) { setStatusMsg('至少需要 3 个点'); return; }
    setSaving(true);
    setStatusMsg(null);
    try {
      const fw = frameW || 1280;
      const fh = frameH || 720;
      const pixelPts = points.map(pt => [Math.round(pt.x * fw), Math.round(pt.y * fh)]);
      const res = await fetch(getApiUrl('/api/v1/focus-zones'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          zone_name: `区域${savedZones.length + 1}`,
          enabled: true,
          polygon_json: JSON.stringify(pixelPts),
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPoints([]);
      setStatusMsg('✓ 区域已保存');
      await fetchZones();
      setTimeout(() => setStatusMsg(null), 2000);
    } catch (e) {
      setStatusMsg('保存失败');
    } finally {
      setSaving(false);
    }
  };

  // ── 清除所有区域 ────────────────────────────────────────────
  const clearAll = async () => {
    if (savedZones.length === 0) return;
    setSaving(true);
    try {
      for (const z of savedZones) {
        await fetch(getApiUrl(`/api/v1/focus-zones/${z.zone_id}`), { method: 'DELETE' });
      }
      setSavedZones([]);
      setPoints([]);
      setStatusMsg('✓ 已清除所有区域');
      setTimeout(() => setStatusMsg(null), 2000);
    } catch (e) {
      setStatusMsg('清除失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          zIndex: 5,
          cursor: active ? 'crosshair' : 'default',
          pointerEvents: active ? 'auto' : 'none',
        }}
      />

      {/* 绘制工具栏 */}
      {active && (
        <div style={toolbarStyles.bar}>
          <span style={toolbarStyles.hint}>
            {points.length === 0
              ? '点击画面添加顶点（至少 3 个）'
              : `已添加 ${points.length} 个点${points.length >= 3 ? '，可保存' : ''}`}
          </span>
          {points.length >= 3 && (
            <button style={toolbarStyles.saveBtn} onClick={() => { void save(); }} disabled={saving}>
              保存区域
            </button>
          )}
          {points.length > 0 && (
            <button style={toolbarStyles.cancelBtn} onClick={() => setPoints([])}>
              重新画
            </button>
          )}
          {savedZones.length > 0 && (
            <button style={toolbarStyles.clearBtn} onClick={() => { void clearAll(); }} disabled={saving}>
              清除所有
            </button>
          )}
          <button style={toolbarStyles.closeBtn} onClick={() => { setPoints([]); onClose(); }}>
            ✕ 关闭
          </button>
          {statusMsg && <span style={toolbarStyles.status}>{statusMsg}</span>}
        </div>
      )}
    </>
  );
};

const toolbarStyles: Record<string, React.CSSProperties> = {
  bar: {
    position: 'absolute',
    bottom: 140, // 抬高，避免被主控制栏遮挡
    left: '50%',
    transform: 'translateX(-50%)',
    zIndex: 50, // 确保持续在最上层
    background: 'rgba(0,0,0,0.82)',
    border: '1px solid rgba(0,255,120,0.4)',
    borderRadius: 8,
    padding: '8px 14px',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    pointerEvents: 'auto',
  },
  hint: {
    fontSize: 12,
    color: 'rgba(0,255,120,0.85)',
    fontFamily: 'monospace',
    whiteSpace: 'nowrap',
  },
  saveBtn: {
    padding: '4px 10px',
    background: 'rgba(0,200,100,0.8)',
    color: '#000',
    border: 'none',
    borderRadius: 5,
    fontWeight: 700,
    fontSize: 12,
    cursor: 'pointer',
  },
  cancelBtn: {
    padding: '4px 10px',
    background: 'rgba(255,200,0,0.25)',
    color: '#fc8',
    border: '1px solid rgba(255,200,0,0.4)',
    borderRadius: 5,
    fontSize: 12,
    cursor: 'pointer',
  },
  clearBtn: {
    padding: '4px 10px',
    background: 'rgba(220,40,40,0.25)',
    color: '#f88',
    border: '1px solid rgba(220,40,40,0.4)',
    borderRadius: 5,
    fontSize: 12,
    cursor: 'pointer',
  },
  closeBtn: {
    padding: '4px 10px',
    background: 'rgba(255,255,255,0.1)',
    color: '#aaa',
    border: '1px solid rgba(255,255,255,0.2)',
    borderRadius: 5,
    fontSize: 12,
    cursor: 'pointer',
  },
  status: {
    fontSize: 11,
    color: '#7f7',
    fontFamily: 'monospace',
  },
};
