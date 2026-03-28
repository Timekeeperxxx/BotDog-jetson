/**
 * AutoTrackPanel — 自动跟踪状态面板（简化版）。
 *
 * 逻辑：
 * - 必须先开始巡检才能启用跟踪
 * - 无手动接管按钮（接管/恢复由控制输入自动触发）
 * - 无暂停/恢复按钮（5 秒无操作后自动恢复）
 */

import React from 'react';
import type { AutoTrackHookState } from '../hooks/useAutoTrack';
import type { AutoTrackStateValue } from '../types/event';

const STATE_LABELS: Record<AutoTrackStateValue, string> = {
  DISABLED: '已禁用',
  IDLE: '待机',
  DETECTING: '侦测中',
  TARGET_LOCKED: '目标锁定',
  FOLLOWING: '跟踪中 ●',
  LOST_SHORT: '目标短时丢失',
  OUT_OF_ZONE_PENDING: '目标出区缓冲',
  MANUAL_OVERRIDE: '已暂停（手动接管）',
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
  PAUSED: '#fa6',
  STOPPED: '#666',
};

interface Props extends AutoTrackHookState {
  isMissionRunning: boolean;
}

export const AutoTrackPanel: React.FC<Props> = ({
  status,
  knownTargets,
  loading,
  error,
  enable,
  disable,
  resume,
  markKnown,
  unmarkKnown,
  isMissionRunning,
}) => {
  const state = status?.state ?? 'DISABLED';
  const stateColor = STATE_COLORS[state] ?? '#666';
  const stateLabel = STATE_LABELS[state] ?? state;
  const isEnabled = status?.enabled ?? false;
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
        {/* 主开关 — 巡检未开始时禁用 */}
        <button
          style={{
            ...styles.toggleBtn,
            background: isEnabled ? '#2bd3' : '#4445',
            color: isEnabled ? '#2bd' : '#888',
            opacity: (!isMissionRunning && !isEnabled) ? 0.4 : 1,
          }}
          onClick={() => (isEnabled ? disable() : enable())}
          disabled={loading || (!isMissionRunning && !isEnabled)}
          title={!isMissionRunning && !isEnabled ? '请先开始巡检' : isEnabled ? '禁用自动跟踪' : '启用自动跟踪'}
        >
          {isEnabled ? '■ 禁用' : '▷ 启用'}
        </button>
      </div>

      {/* 巡检未开始提示 */}
      {!isMissionRunning && !isEnabled && (
        <div style={styles.hintBar}>请先点击「开始巡检」</div>
      )}


      {/* 错误提示 */}
      {error && (
        <div style={styles.errorBar}>{error}</div>
      )}

      {/* 恢复按钮 */}
      {isEnabled && (state === 'PAUSED' || state === 'MANUAL_OVERRIDE') && (
        <button
          style={{
            width: '100%', padding: '6px 0', borderRadius: 4, fontWeight: 600,
            cursor: 'pointer', marginBottom: 6,
            background: '#fa63', color: '#fc8', border: '1px solid #fa66'
          }}
          onClick={() => resume()}
          disabled={loading}
          title="手动接管后重新开始自动跟踪"
        >
          ▶ 恢复跟踪
        </button>
      )}

      {/* 当前目标 */}
      {target ? (
        <div style={styles.targetBox}>
          <div style={styles.targetTitle}>🎯 跟踪目标 #{target.track_id}</div>
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
  hintBar: {
    background: '#4443',
    color: '#888',
    borderRadius: 4,
    padding: '4px 8px',
    marginBottom: 6,
    fontSize: 11,
    textAlign: 'center',
  },
  pausedBar: {
    background: '#fa62a',
    color: '#fc8',
    borderRadius: 4,
    padding: '4px 8px',
    marginBottom: 6,
    fontSize: 11,
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
};
