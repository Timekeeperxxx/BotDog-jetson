/**
 * TrackOverlay — YOLO 检测框 + 决策区域可视化叠层。
 *
 * 叠加在主视频 <video> 上方的 canvas，实时绘制：
 * 1. 所有检测到的 person bbox（绿色）
 * 2. 当前锁定目标的 bbox（红色加粗）
 * 3. 水平死区中线（蓝色虚线）
 * 4. 纵向停止线（黄色虚线）
 * 5. 当前决策文字（左上角）
 */

import { useEffect, useRef, useCallback } from 'react';
import {
  DEFAULT_AI_OVERLAY_VISIBILITY,
  type AiOverlayVisibility,
} from './video/videoStagePreferences';

export interface TrackOverlayData {
  detections?: {
    bbox: number[];
    conf: number;
    class_name?: string;
    track_id?: number;
    is_stranger?: boolean | null;
    safety_status?: string | null;
    identity_id?: number | null;
    display_name?: string | null;
    face_status?: 'pending' | 'recognized' | 'unknown' | 'unavailable' | null;
    face_score?: number | null;
    fence_behavior?: string | null;
    fence_action_score?: number;
    fence_structure_change_ratio?: number;
  }[];
  poses?: {
    track_id: number;
    bbox: number[];
    confidence: number;
    posture: string;
    posture_confidence: number;
    inside_zone: boolean;
    dwell_seconds: number;
    keypoints: number[][];
  }[];
  keypoint_confidence?: number;
  persons: {
    bbox: number[];
    conf: number;
    class_name?: string;
    track_id?: number;
    is_stranger?: boolean;
    safety_status?: string | null;
    identity_id?: number | null;
    display_name?: string | null;
    face_status?: 'pending' | 'recognized' | 'unknown' | 'unavailable' | null;
    face_score?: number | null;
    fence_behavior?: string | null;
    fence_action_score?: number;
    fence_structure_change_ratio?: number;
  }[];
  active_bbox: number[] | null;
  zone_bbox?: number[] | null;        // 防区 bounding box [x1,y1,x2,y2]
  zone_polygon?: number[][] | null;   // 防区旋转四边形 [[x,y],[x,y],[x,y],[x,y]]
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
  edge_margin_ratio?: number;  // 边缘裕量比例，来自 GUARD_ZONE_EDGE_MARGIN_RATIO
}

interface Props {
  data: TrackOverlayData | null;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  visibility?: AiOverlayVisibility;
}

export function TrackOverlay({
  data,
  videoRef,
  visibility = DEFAULT_AI_OVERLAY_VISIBILITY,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number>(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const video = videoRef.current;
    if (!canvas || !video) return;

    const parent = canvas.parentElement;
    if (!parent) return;

    // canvas 覆盖 parent 的全部尺寸
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

    const sx = cw / data.frame_w;
    const sy = ch / data.frame_h;

    if (visibility.tracking) {
      // ─── 1. 水平死区（两条蓝色虚线） ─────────────────────────────
      const centerX = cw / 2;
      const dbPx = data.deadband_px * sx;
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

      // ─── 2. 纵向停止线（黄色虚线） ────────────────────────────────
      const stopY = data.anchor_y_stop_ratio * ch;
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
    }

    const allDetections = data.detections?.length
      ? data.detections
      : data.persons.map((p) => ({ ...p, class_name: p.class_name || 'person' }));

    const overlayDetections = allDetections.filter((detection) => {
      const className = detection.class_name || 'person';
      if (className === 'guns' || className === 'knife') return visibility.weapon;
      if (className === 'head' || className === 'helmet') return visibility.helmet;
      if (className === 'person') {
        return visibility.helmet || (visibility.face && Boolean(detection.face_status));
      }
      return visibility.helmet;
    });

    const visiblePoses = visibility.pose ? (data.poses ?? []) : [];
    const postureLabels: Record<string, string> = {
      standing: '站立',
      crouching: '蹲伏',
      lying: '倒地/躺卧',
      climbing_suspected: '疑似攀爬',
      unknown: '姿态待确认',
    };
    const postureColors: Record<string, string> = {
      standing: 'rgba(50,220,180,0.95)',
      crouching: 'rgba(255,180,40,0.98)',
      lying: 'rgba(255,70,70,0.98)',
      climbing_suspected: 'rgba(255,40,120,0.98)',
      unknown: 'rgba(180,190,210,0.8)',
    };

    type LabelLine = {
      text: string;
      background: string;
      color: string;
      font?: string;
    };

    const fitLabelText = (text: string, maxWidth: number) => {
      if (ctx.measureText(text).width <= maxWidth) return text;
      const ellipsis = '…';
      if (ctx.measureText(ellipsis).width > maxWidth) return '';

      let low = 0;
      let high = text.length;
      while (low < high) {
        const middle = Math.ceil((low + high) / 2);
        if (ctx.measureText(`${text.slice(0, middle)}${ellipsis}`).width <= maxWidth) {
          low = middle;
        } else {
          high = middle - 1;
        }
      }
      return `${text.slice(0, low)}${ellipsis}`;
    };

    const drawLabelsInsideBox = (
      boxX: number,
      boxY: number,
      boxWidth: number,
      boxHeight: number,
      lines: LabelLine[],
      placement: 'top' | 'bottom',
    ) => {
      const rowHeight = 16;
      const paddingX = 4;
      const availableRows = Math.max(0, Math.floor(boxHeight / rowHeight));
      const visibleLines = lines.filter((line) => line.text).slice(0, availableRows);
      if (boxWidth < 8 || visibleLines.length === 0) return;

      const stackHeight = visibleLines.length * rowHeight;
      const startY = placement === 'top' ? boxY : boxY + boxHeight - stackHeight;
      visibleLines.forEach((line, index) => {
        ctx.font = line.font ?? 'bold 10px monospace';
        const fittedText = fitLabelText(line.text, Math.max(0, boxWidth - paddingX * 2));
        if (!fittedText) return;
        const rowY = startY + index * rowHeight;
        const backgroundWidth = Math.min(
          boxWidth,
          ctx.measureText(fittedText).width + paddingX * 2,
        );
        ctx.fillStyle = line.background;
        ctx.fillRect(boxX, rowY, backgroundWidth, rowHeight);
        ctx.fillStyle = line.color;
        ctx.fillText(fittedText, boxX + paddingX, rowY + 12);
      });
    };

    const bboxIou = (first: number[], second: number[]) => {
      if (first.length !== 4 || second.length !== 4) return 0;
      const intersectionWidth = Math.max(0, Math.min(first[2], second[2]) - Math.max(first[0], second[0]));
      const intersectionHeight = Math.max(0, Math.min(first[3], second[3]) - Math.max(first[1], second[1]));
      const intersection = intersectionWidth * intersectionHeight;
      const firstArea = Math.max(0, first[2] - first[0]) * Math.max(0, first[3] - first[1]);
      const secondArea = Math.max(0, second[2] - second[0]) * Math.max(0, second[3] - second[1]);
      const union = firstArea + secondArea - intersection;
      return union > 0 ? intersection / union : 0;
    };

    // 姿态模型与人员检测模型会为同一个人产生近似外框。按 IoU 一对一合并，
    // 将姿态结果放进人员框中，避免重复边框和标签互相遮挡。
    const poseByDetectionIndex = new Map<number, number>();
    const matchedPoseIndexes = new Set<number>();
    overlayDetections.forEach((detection, detectionIndex) => {
      if ((detection.class_name || 'person') !== 'person') return;
      let bestPoseIndex = -1;
      let bestIou = 0;
      visiblePoses.forEach((pose, poseIndex) => {
        if (matchedPoseIndexes.has(poseIndex)) return;
        const iou = bboxIou(detection.bbox, pose.bbox);
        if (iou > bestIou) {
          bestIou = iou;
          bestPoseIndex = poseIndex;
        }
      });
      if (bestPoseIndex >= 0 && bestIou >= 0.25) {
        poseByDetectionIndex.set(detectionIndex, bestPoseIndex);
        matchedPoseIndexes.add(bestPoseIndex);
      }
    });

    const colorForClass = (className: string, isStranger?: boolean | null, safetyStatus?: string | null) => {
      if (className === 'person') {
        if (safetyStatus === 'no_helmet') {
          return {
            box: 'rgba(255,45,45,0.95)',
            label: 'rgba(160,20,20,0.94)',
          };
        }
        const isKnown = isStranger === false;
        return {
          box: isKnown ? 'rgba(0,220,120,0.85)' : 'rgba(255,100,0,0.9)',
          label: isKnown ? 'rgba(0,100,50,0.9)' : 'rgba(150,40,0,0.9)',
        };
      }
      if (className === 'head') {
        return { box: 'rgba(70,170,255,0.9)', label: 'rgba(20,80,150,0.92)' };
      }
      if (className === 'helmet') {
        return { box: 'rgba(255,220,40,0.95)', label: 'rgba(150,120,0,0.92)' };
      }
      if (className === 'guns') {
        return { box: 'rgba(255,30,30,0.98)', label: 'rgba(150,0,0,0.96)' };
      }
      if (className === 'knife') {
        return { box: 'rgba(255,45,180,0.98)', label: 'rgba(140,0,85,0.96)' };
      }
      return { box: 'rgba(220,220,220,0.85)', label: 'rgba(80,80,80,0.92)' };
    };

    // ─── 3. 所有 YOLO 检测框：person / head / helmet / weapon ──────
    for (const [detectionIndex, p] of overlayDetections.entries()) {
      if (!Array.isArray(p.bbox) || p.bbox.length !== 4) continue;

      const [x1, y1, x2, y2] = p.bbox;
      const rx = x1 * sx, ry = y1 * sy;
      const rw = (x2 - x1) * sx, rh = (y2 - y1) * sy;
      const className = p.class_name || 'person';
      const visibleSafetyStatus = visibility.helmet ? p.safety_status : null;
      const visibleStrangerStatus = visibility.face ? p.is_stranger : null;
      const colors = colorForClass(className, visibleStrangerStatus, visibleSafetyStatus);
      const fenceLabels: Record<string, string> = {
        approaching: '靠近围栏',
        dwelling: '围栏徘徊',
        contact: '接触围栏',
        climbing_suspected: '疑似翻越',
        tampering_suspected: '疑似破坏围栏',
        tampering_confirmed: '确认破坏围栏',
      };
      const fenceLabel = className === 'person' && p.fence_behavior
        ? fenceLabels[p.fence_behavior] ?? ''
        : '';
      const isFenceTamper = p.fence_behavior === 'tampering_suspected'
        || p.fence_behavior === 'tampering_confirmed';

      ctx.save();
      ctx.strokeStyle = isFenceTamper ? 'rgba(255,45,45,0.98)' : colors.box;
      ctx.lineWidth = isFenceTamper ? 3 : (className === 'person' ? 1.8 : 1.5);
      ctx.strokeRect(rx, ry, rw, rh);

      const idPart = p.track_id !== undefined && p.track_id >= 0 ? ` #${p.track_id}` : '';
      const faceLabel = visibility.face && className === 'person'
        ? (p.face_status === 'recognized' && p.display_name
          ? ` · ${p.display_name}`
          : p.face_status === 'unknown'
            ? ' · 未授权'
            : p.face_status === 'pending'
              ? ' · 识别中'
              : p.face_status === 'unavailable'
                ? ' · 未授权'
                : '')
        : '';
      const classLabels: Record<string, string> = {
        person: '人员',
        helmet: '安全帽',
        guns: '枪械',
        knife: '刀具',
      };
      const baseLabel = className === 'person' && !visibility.helmet && visibility.face
        ? '人脸'
        : (classLabels[className] ?? className);
      const fencePart = fenceLabel ? ` · ${fenceLabel}` : '';
      const headerText = `${baseLabel}${idPart}${faceLabel}${fencePart} ${(p.conf * 100).toFixed(0)}%`;
      const showNoHelmetTag = visibility.helmet && p.safety_status === 'no_helmet';
      const showIdentityTag = visibility.face && p.is_stranger !== undefined && p.is_stranger !== null;
      const labelLines: LabelLine[] = [{
        text: headerText,
        background: colors.label,
        color: '#fff',
      }];

      const matchedPoseIndex = poseByDetectionIndex.get(detectionIndex);
      if (className === 'person' && matchedPoseIndex !== undefined) {
        const pose = visiblePoses[matchedPoseIndex];
        const poseColor = postureColors[pose.posture] ?? postureColors.unknown;
        labelLines.push({
          text: `姿态：${postureLabels[pose.posture] ?? pose.posture} ${(pose.posture_confidence * 100).toFixed(0)}%`,
          background: 'rgba(10,10,15,0.78)',
          color: poseColor,
          font: 'bold 10px sans-serif',
        });
      }

      if (className === 'person' && (showNoHelmetTag || showIdentityTag)) {
        const statusParts: string[] = [];
        if (showNoHelmetTag) statusParts.push('未戴安全帽');
        if (showIdentityTag) statusParts.push(p.is_stranger ? '未授权' : '已授权');
        labelLines.push({
          text: statusParts.join(' · '),
          background: showNoHelmetTag || p.is_stranger
            ? 'rgba(220,0,0,0.88)'
            : 'rgba(0,150,75,0.88)',
          color: '#fff',
        });
      }

      // 人员信息放在框内底部，以避开人员头部区域中的 head / helmet 子框；
      // 其余目标的标签放在各自检测框内顶部。
      drawLabelsInsideBox(
        rx,
        ry,
        rw,
        rh,
        labelLines,
        className === 'person' ? 'bottom' : 'top',
      );

      ctx.restore();
    }

    // ─── 3.2. COCO 17 点人体骨架与姿态标签 ──────────────────────
    const skeletonEdges = [
      [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
      [5, 11], [6, 12], [11, 12],
      [11, 13], [13, 15], [12, 14], [14, 16],
      [0, 1], [0, 2], [1, 3], [2, 4],
    ];
    const keypointThreshold = data.keypoint_confidence ?? 0.35;

    for (const [poseIndex, pose] of visiblePoses.entries()) {
      const color = postureColors[pose.posture] ?? postureColors.unknown;
      const points = pose.keypoints;
      ctx.save();
      // 姿态骨架在检测标签之后绘制时使用底层合成，避免骨架线覆盖人员文字。
      ctx.globalCompositeOperation = 'destination-over';
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 2;

      for (const [startIndex, endIndex] of skeletonEdges) {
        const start = points[startIndex];
        const end = points[endIndex];
        if (
          !start || !end
          || (start[2] ?? 0) < keypointThreshold
          || (end[2] ?? 0) < keypointThreshold
        ) continue;
        ctx.beginPath();
        ctx.moveTo(start[0] * sx, start[1] * sy);
        ctx.lineTo(end[0] * sx, end[1] * sy);
        ctx.stroke();
      }

      for (const point of points) {
        if (!point || (point[2] ?? 0) < keypointThreshold) continue;
        ctx.beginPath();
        ctx.arc(point[0] * sx, point[1] * sy, 2.5, 0, Math.PI * 2);
        ctx.fill();
      }

      // 已匹配的姿态信息已经合并进人员框，不再重复绘制姿态外框。
      if (!matchedPoseIndexes.has(poseIndex) && Array.isArray(pose.bbox) && pose.bbox.length === 4) {
        const [x1, y1, x2, y2] = pose.bbox;
        const rx = x1 * sx;
        const ry = y1 * sy;
        const rw = (x2 - x1) * sx;
        const rh = (y2 - y1) * sy;
        ctx.globalCompositeOperation = 'source-over';
        ctx.setLineDash([5, 3]);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = color;
        ctx.strokeRect(rx, ry, rw, rh);
        ctx.setLineDash([]);
        drawLabelsInsideBox(rx, ry, rw, rh, [{
          text: `姿态：${postureLabels[pose.posture] ?? pose.posture} ${(pose.posture_confidence * 100).toFixed(0)}% #${pose.track_id}`,
          background: 'rgba(10,10,15,0.78)',
          color,
          font: 'bold 10px sans-serif',
        }], 'bottom');
      }
      ctx.restore();
    }

    // ─── 3.5. 人的脚点记录 ──────────────────────────────────────
    if (visibility.tracking && data.foot_points && data.foot_points.length > 0) {
      for (const fp of data.foot_points) {
        const fx = fp.x * sx;
        const fy = fp.y * sy;
        ctx.save();
        ctx.beginPath();
        ctx.arc(fx, fy, 4, 0, Math.PI * 2);
        ctx.fillStyle = fp.in_zone ? 'rgba(255,50,50,0.9)' : 'rgba(0,220,120,0.7)';
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

    // ─── 3.8. 边缘裕量保护区（红色半透明条带 + 三侧安全边界线） ──────────
    if (visibility.tracking && data.edge_margin_ratio && data.edge_margin_ratio > 0) {
      const mx = cw * data.edge_margin_ratio;
      const my = ch * data.edge_margin_ratio;
      const dangerColor = 'rgba(255, 60, 60, 0.13)';
      const borderColor = 'rgba(255, 100, 80, 0.7)';

      ctx.save();

      // 三条危险边带：左 / 右 / 下
      ctx.fillStyle = dangerColor;
      ctx.fillRect(0, 0, mx, ch);                  // 左
      ctx.fillRect(cw - mx, 0, mx, ch);            // 右
      ctx.fillRect(0, ch - my, cw, my);            // 下

      // 三条安全边界虚线（只画左/右/下，不画顶部避免误导）
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(mx, 0);      ctx.lineTo(mx, ch - my);       // 左边界
      ctx.moveTo(cw - mx, 0); ctx.lineTo(cw - mx, ch - my);  // 右边界
      ctx.moveTo(mx, ch - my); ctx.lineTo(cw - mx, ch - my); // 下边界
      ctx.stroke();

      // 标签
      ctx.setLineDash([]);
      ctx.fillStyle = borderColor;
      ctx.font = '9px monospace';
      ctx.fillText(`安全边界 ${Math.round(data.edge_margin_ratio * 100)}%`, mx + 4, ch - my - 4);

      ctx.restore();
    }

    // ─── 4. 防区多边形（黄色，优先画旋转四边形） ─────────────────────
    if (visibility.tracking && data.zone_polygon && data.zone_polygon.length >= 3) {
      // 精确旋转四边形
      const pts = data.zone_polygon.map(([px, py]) => [px * sx, py * sy]);
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
      ctx.fillText('🟡 防区(颜色检测)', pts[0][0] + 3, pts[0][1] - 5);
      ctx.restore();
    } else if (visibility.tracking && data.zone_bbox) {
      // 回退：轴对齐矩形
      const [x1, y1, x2, y2] = data.zone_bbox;
      const rx = x1 * sx, ry = y1 * sy;
      const rw = (x2 - x1) * sx, rh = (y2 - y1) * sy;

      ctx.save();
      ctx.setLineDash([6, 3]);
      ctx.strokeStyle = 'rgba(255, 220, 0, 0.9)';
      ctx.lineWidth = 2;
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.fillStyle = 'rgba(255, 220, 0, 0.12)';
      ctx.fillRect(rx, ry, rw, rh);

      ctx.fillStyle = 'rgba(255,220,0,0.95)';
      ctx.font = 'bold 11px monospace';
      ctx.fillText('🟡 防区', rx + 3, ry - 5);
      ctx.restore();
    }

    // ─── 6. 锁定目标（红色加粗框） ──────────────────────────────────
    if (visibility.tracking && data.active_bbox) {
      const [x1, y1, x2, y2] = data.active_bbox;
      const rx = x1 * sx, ry = y1 * sy;
      const rw = (x2 - x1) * sx, rh = (y2 - y1) * sy;

      ctx.save();
      ctx.strokeStyle = 'rgba(255,60,60,0.85)';
      ctx.lineWidth = 2.5;
      ctx.strokeRect(rx, ry, rw, rh);

      // 锁定状态标签框
      const stateBadge = data.state && data.state !== 'IDLE' ? data.state : 'TRACKING';
      const badgeW = ctx.measureText(stateBadge).width + 30; // 预估宽度

      ctx.fillStyle = 'rgba(255,40,40,0.9)';
      ctx.fillRect(rx, ry - 18, Math.max(badgeW, 80), 18);
      ctx.fillStyle = '#fff';
      ctx.font = 'bold 11px monospace';
      ctx.fillText(`🎯 ${stateBadge}`, rx + 4, ry - 5);

      // anchor 点（底部中心）
      const anchorX = (x1 + x2) / 2 * sx;
      const anchorY = y2 * sy;
      ctx.beginPath();
      ctx.arc(anchorX, anchorY, 4, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,100,0,0.9)';
      ctx.fill();
      ctx.restore();
    }

    // ─── 5. 决策信息（左下角） ───────────────────────────────────────
    if (visibility.tracking && (data.command || data.state)) {
      const cmdLabel: Record<string, string> = {
        forward: '↑ 前进', left: '← 左转', right: '→ 右转', stop: '■ 停止',
      };
      const cmdText = data.command ? (cmdLabel[data.command] || data.command) : '';
      const stateText = data.state || '';

      ctx.save();
      // 背景
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.fillRect(4, ch - 52, 320, 48);

      // 状态
      ctx.fillStyle = '#aaa';
      ctx.font = '10px monospace';
      ctx.fillText(`状态: ${stateText}  |  目标: ${overlayDetections.length}  人: ${data.persons.length}`, 10, ch - 36);

      // 决策命令
      if (cmdText) {
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 13px monospace';
        ctx.fillText(cmdText, 10, ch - 20);
      }
      // 原因
      if (data.reason) {
        ctx.fillStyle = '#8cf';
        ctx.font = '10px monospace';
        ctx.fillText(data.reason.slice(0, 45), 90, ch - 20);
      }
      ctx.restore();
    }
  }, [data, videoRef, visibility]);

  useEffect(() => {
    draw();
  }, [draw]);

  // 窗口 resize 时重绘
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
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        zIndex: 2,
      }}
    />
  );
}
