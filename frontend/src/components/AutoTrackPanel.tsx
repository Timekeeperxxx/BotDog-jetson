/**
 * AutoTrackPanel — 自动跟踪状态面板。
 *
 * 功能：
 * - 显示当前自动跟踪状态（IDLE/DETECTING/FOLLOWING 等）
 * - 显示控制权拥有者（AUTO_TRACK / WEB_MANUAL / E_STOP 等）
 * - 提供启用/禁用开关
 * - 提供人工接管/释放按钮
 * - 显示当前活跃目标信息和候选数量
 * - 显示已知人员列表，支持取消标记
 */

import React from 'react';
import type { AutoTrackHookState } from '../hooks/useAutoTrack';
import type { AutoTrackStateValue } from '../types/event';

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const STATE_LABELS: Record<AutoTrackStateValue, string> = {
  DISABLED: '已禁用',
  IDLE: '待机',
  DETECTING: '侦测中',
  TARGET_LOCKED: '目标锁定',
  FOLLOWING: '跟踪中 ●',
  LOST_SHORT: '目标短时丢失',
  OUT_OF_ZONE_PENDING: '目标出区缓冲',
  MANUAL_OVERRIDE: '人工接管',
  PAUSED: '已暂停',
  STOPPED: '已停止',
};

const STATE_COLORS: Record<AutoTrackStateValue, string> = {
  DISABLED: '#666',
  IDLE: '#888',
  DETECTING: '#f0a500',
  TARGET_LOCKED: '#e55',
  FOLLOWING: '#2bd',
  LOST_SHORT: '#e88',
  OUT_OF_ZONE_PENDING: '#fa6',
  MANUAL_OVERRIDE: '#c8f',
  PAUSED: '#999',
  STOPPED: '#666',
};

const OWNER_LABELS: Record<string, string> = {
  NONE: '无',
  AUTO_TRACK: '自动跟踪',
  WEB_MANUAL: 'Web 手动',
  REMOTE_CONTROLLER: '遥控器',
  E_STOP: '紧急停止',
};

// ─── 组件 ─────────────────────────────────────────────────────────────────────

interface Props extends AutoTrackHookState {}

const CMD_COLORS: Record<string, string> = {
  forward:  '#2bd',
  left:     '#fa6',
  right:    '#f6a',
  stop:     '#888',
};

export const AutoTrackPanel: React.FC<Props> = ({
  status,
  knownTargets,
  loading,
  error,
  trackDecision,
  enable,
  disable,
  pause,
  resume,
  manualOverride,
  releaseOverride,
  markKnown,
  unmarkKnown,
}) => {
  const state = status?.state ?? 'DISABLED';
  const stateColor = STATE_COLORS[state] ?? '#666';
  const stateLabel = STATE_LABELS[state] ?? state;
  const isEnabled = status?.enabled ?? false;
  const isManualOverride = state === 'MANUAL_OVERRIDE';
  const owner = status?.control_arbiter?.owner ?? 'NONE';
  const canAutoTrack = status?.control_arbiter?.can_auto_track ?? false;
  const target = status?.active_target;
  const candidateCount = status?.candidate_count ?? 0;

  return (
    <div style={styles.container}>
      {/* 标题行 */}
      <div style={styles.header}>
        <span style={{ ...styles.dot, background: stateColor }} />
        <span style={styles.title}>自动跟踪</span>
        <span style={{ ...styles.stateBadge, background: stateColor + '33', color: stateColor }}>
          {stateLabel}
        </span>
        {/* 主开关 */}
        <button
          style={{
            ...styles.toggleBtn,
            background: isEnabled ? '#2bd3' : '#4445',
            color: isEnabled ? '#2bd' : '#888',
          }}
          onClick={() => (isEnabled ? disable() : enable())}
          disabled={loading}
          title={isEnabled ? '禁用自动跟踪' : '启用自动跟踪'}
        >
          {isEnabled ? '■ 禁用' : '▷ 启用'}
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div style={styles.errorBar}>{error}</div>
      )}

      {/* 控制权行 */}
      <div style={styles.row}>
        <span style={styles.label}>控制权</span>
        <span style={{
          ...styles.value,
          color: owner === 'AUTO_TRACK' ? '#2bd' : owner === 'E_STOP' ? '#e55' : '#fa6',
        }}>
          {OWNER_LABELS[owner] ?? owner}
        </span>
        {/* 人工接管 / 释放 */}
        {isEnabled && (
          isManualOverride || !canAutoTrack ? (
            <button style={styles.smallBtn} onClick={releaseOverride} disabled={loading}>
              释放
            </button>
          ) : (
            <button style={{ ...styles.smallBtn, background: '#fa63' }} onClick={manualOverride} disabled={loading}>
              接管
            </button>
          )
        )}
      </div>

      {/* 暂停/恢复 */}
      {isEnabled && (
        <div style={styles.row}>
          <span style={styles.label}>跟踪控制</span>
          <button style={styles.smallBtn} onClick={pause} disabled={loading || state === 'PAUSED'}>
            暂停
          </button>
          <button style={{ ...styles.smallBtn, marginLeft: 4 }} onClick={resume} disabled={loading || state !== 'PAUSED'}>
            恢复
          </button>
        </div>
      )}

      {/* 当前目标信息 (精简版) */}
      {target ? (
        <div style={styles.targetBox}>
          <div style={styles.targetTitle}>🎯 活跃目标 #{target.track_id}</div>
          {/* 标记为已知人员 */}
          <button
            style={{ ...styles.smallBtn, marginTop: 2, background: '#8844aa44', color: '#c8f' }}
            onClick={() => markKnown(target.track_id)}
            disabled={loading}
            title="将当前目标标记为已知人员，不再跟踪"
          >
            👤 标记为已知
          </button>
        </div>
      ) : (
        isEnabled && (
          <div style={styles.row}>
            <span style={styles.label}>候选目标</span>
            <span style={styles.value}>{candidateCount} 个</span>
          </div>
        )
      )}

      {/* 已知人员列表 */}
      {knownTargets.length > 0 && (
        <div style={styles.knownList}>
          <div style={styles.label}>已知人员（{knownTargets.length}）</div>
          {knownTargets.map(kt => (
            <span key={kt.track_id} style={styles.knownTag}>
              #{kt.track_id}
              <button
                style={styles.knownRemoveBtn}
                onClick={() => unmarkKnown(kt.track_id)}
                title="取消标记"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

// ─── 样式 ─────────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: 'rgba(10,20,35,0.85)',
    border: '1px solid #1e3a5a',
    borderRadius: 8,
    padding: '10px 12px',
    fontSize: 12,
    color: '#cdd',
    minWidth: 220,
    maxWidth: 280,
    boxShadow: '0 2px 12px rgba(0,0,0,0.4)',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 8,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    flexShrink: 0,
  },
  title: {
    fontWeight: 600,
    fontSize: 13,
    color: '#eef',
    flexGrow: 1,
  },
  stateBadge: {
    fontSize: 10,
    padding: '2px 6px',
    borderRadius: 10,
    fontWeight: 600,
  },
  toggleBtn: {
    padding: '3px 8px',
    borderRadius: 5,
    border: 'none',
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 600,
    transition: 'all 0.15s',
  },
  errorBar: {
    background: '#e553',
    color: '#faa',
    borderRadius: 4,
    padding: '4px 8px',
    marginBottom: 6,
    fontSize: 11,
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 4,
  },
  label: {
    color: '#7a9',
    minWidth: 52,
    flexShrink: 0,
  },
  value: {
    color: '#cdd',
    flexGrow: 1,
  },
  smallBtn: {
    background: '#1a3a5a',
    color: '#adf',
    border: '1px solid #2a5a8a',
    borderRadius: 4,
    padding: '2px 8px',
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 500,
  },
  targetBox: {
    background: 'rgba(43,221,200,0.06)',
    border: '1px solid #2bd4',
    borderRadius: 6,
    padding: '8px 10px',
    marginTop: 6,
    marginBottom: 6,
  },
  targetTitle: {
    fontWeight: 600,
    color: '#2bd',
    marginBottom: 6,
  },
  targetRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 3,
  },
  knownList: {
    marginTop: 6,
    display: 'flex',
    flexWrap: 'wrap',
    gap: 4,
    alignItems: 'center',
  },
  knownTag: {
    background: '#8844aa33',
    border: '1px solid #c8f4',
    color: '#c8f',
    borderRadius: 10,
    padding: '2px 8px',
    fontSize: 11,
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
  },
  knownRemoveBtn: {
    background: 'none',
    border: 'none',
    color: '#c8f',
    cursor: 'pointer',
    padding: '0 2px',
    fontSize: 14,
    lineHeight: 1,
    fontWeight: 700,
  },
  debugRow: {
    display: 'flex',
    gap: 10,
    fontSize: 10,
    color: '#567',
    marginTop: 6,
    borderTop: '1px solid #1e3a5a',
    paddingTop: 4,
  },
  decisionBox: {
    background: 'rgba(43,180,200,0.06)',
    border: '1px solid rgba(43,189,200,0.25)',
    borderRadius: 6,
    padding: '7px 10px',
    marginTop: 6,
    marginBottom: 2,
  },
  decisionTitle: {
    fontSize: 10,
    color: '#7cc',
    fontWeight: 600,
    marginBottom: 5,
  },
  decisionRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  decisionReason: {
    fontSize: 10,
    color: '#78a',
    lineHeight: 1.4,
    wordBreak: 'break-word' as const,
  },
  cmdBadge: {
    fontSize: 11,
    fontWeight: 700,
    padding: '2px 10px',
    borderRadius: 10,
  },
};

