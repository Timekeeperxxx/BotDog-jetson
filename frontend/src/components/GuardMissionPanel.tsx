/**
 * GuardMissionPanel — 自动驱离任务控制面板。
 *
 * 功能：
 * - 开启 / 关闭 驱离任务
 * - 实时轮询显示任务状态：state, intrusion_counter, clear_counter, guard_duration_s
 * - 紧急中止按钮（DEPLOYING/GUARDING 阶段可用）
 */

import React, { useEffect, useState, useCallback } from 'react';
import { getApiUrl } from '../config/api';

export interface GuardStatus {
  enabled: boolean;
  state: string;
  intrusion_counter: number;
  confirm_frames: number;
  clear_counter: number;
  clear_frames: number;
  guard_duration_s: number;
}

const STATE_LABEL: Record<string, string> = {
  STANDBY:         '待机中',
  DEPLOYING:       '前往驱离点',
  GUARDING:        '驱离中',
  RETURNING:       '返回原点',
  MANUAL_OVERRIDE: '手动接管',
  FAULT:           '故障',
};

const STATE_COLOR: Record<string, string> = {
  STANDBY:         '#528',
  DEPLOYING:       '#f80',
  GUARDING:        '#e44',
  RETURNING:       '#2bd',
  MANUAL_OVERRIDE: '#c8f',
  FAULT:           '#f44',
};

interface Props {
  onStatusChange?: (status: GuardStatus | null) => void;
}

export const GuardMissionPanel: React.FC<Props> = ({ onStatusChange }) => {
  const [status, setStatus] = useState<GuardStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 定时轮询状态（1.5 秒一次）
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(getApiUrl('/api/v1/guard-mission/status'));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: GuardStatus = await res.json();
      setStatus(data);
      onStatusChange?.(data);
      setError(null);
    } catch (e) {
      setError('状态获取失败');
      onStatusChange?.(null);
    }
  }, [onStatusChange]);

  useEffect(() => {
    void fetchStatus();
    const timer = setInterval(() => { void fetchStatus(); }, 1500);
    return () => clearInterval(timer);
  }, [fetchStatus]);

  const toggle = async () => {
    if (loading) return;
    setLoading(true);
    try {
      const endpoint = status?.enabled ? '/api/v1/guard-mission/disable' : '/api/v1/guard-mission/enable';
      const res = await fetch(getApiUrl(endpoint), { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await fetchStatus();
    } catch (e) {
      setError('操作失败');
    } finally {
      setLoading(false);
    }
  };

  const abort = async () => {
    if (loading) return;
    setLoading(true);
    try {
      await fetch(getApiUrl('/api/v1/guard-mission/abort'), { method: 'POST' });
      await fetchStatus();
    } catch (e) {
      setError('中止失败');
    } finally {
      setLoading(false);
    }
  };

  const state = status?.state ?? 'STANDBY';
  const stateLabel = STATE_LABEL[state] ?? state;
  const stateColor = STATE_COLOR[state] ?? '#666';
  const isEnabled = status?.enabled ?? false;
  const isActive = ['DEPLOYING', 'GUARDING', 'RETURNING'].includes(state);

  return (
    <div style={styles.container}>
      {/* 标题行 */}
      <div style={styles.header}>
        <span style={{ ...styles.dot, background: isEnabled ? stateColor : '#444' }} />
        <span style={styles.title}>🛡 自动驱离</span>
        <span style={{ ...styles.badge, background: stateColor + '33', color: stateColor }}>
          {stateLabel}
        </span>
        <button
          style={{
            ...styles.toggleBtn,
            background: isEnabled ? '#e443' : '#2bd3',
            color: isEnabled ? '#f88' : '#2bd',
          }}
          onClick={() => { void toggle(); }}
          disabled={loading}
        >
          {isEnabled ? '■ 关闭' : '▷ 开启'}
        </button>
      </div>

      {/* 错误提示 */}
      {error && <div style={styles.errorBar}>{error}</div>}

      {/* 状态数值 */}
      {isEnabled && status && (
        <div style={styles.statsBox}>
          <div style={styles.row}>
            <span style={styles.label}>入侵计数</span>
            <span style={{ ...styles.value, color: status.intrusion_counter > 0 ? '#f80' : '#cdd' }}>
              {status.intrusion_counter} / {status.confirm_frames}
            </span>
          </div>
          {isActive && (
            <>
              <div style={styles.row}>
                <span style={styles.label}>清空计数</span>
                <span style={{ ...styles.value, color: status.clear_counter > 0 ? '#2bd' : '#cdd' }}>
                  {status.clear_counter} / {status.clear_frames}
                </span>
              </div>
              <div style={styles.row}>
                <span style={styles.label}>驱离时长</span>
                <span style={styles.value}>{status.guard_duration_s.toFixed(1)} s</span>
              </div>
            </>
          )}
        </div>
      )}

      {/* 紧急中止按钮 */}
      {isActive && (
        <button
          style={styles.abortBtn}
          onClick={() => { void abort(); }}
          disabled={loading}
        >
          ⚠ 紧急中止
        </button>
      )}
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  container: {
    background: 'rgba(10,5,20,0.88)',
    border: '1px solid #3a1a5a',
    borderRadius: 8,
    padding: '10px 12px',
    fontSize: 12,
    color: '#cdd',
    minWidth: 220,
    maxWidth: 280,
    boxShadow: '0 2px 12px rgba(0,0,0,0.5)',
    marginTop: 6,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    marginBottom: 6,
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
  badge: {
    fontSize: 10,
    padding: '2px 5px',
    borderRadius: 10,
    fontWeight: 600,
    whiteSpace: 'nowrap',
  },
  toggleBtn: {
    padding: '3px 8px',
    borderRadius: 5,
    border: 'none',
    cursor: 'pointer',
    fontSize: 11,
    fontWeight: 600,
    transition: 'all 0.15s',
    whiteSpace: 'nowrap',
  },
  errorBar: {
    background: '#e553',
    color: '#faa',
    borderRadius: 4,
    padding: '3px 8px',
    marginBottom: 4,
    fontSize: 11,
  },
  statsBox: {
    background: 'rgba(255,255,255,0.04)',
    borderRadius: 5,
    padding: '6px 8px',
    marginBottom: 6,
  },
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    marginBottom: 3,
  },
  label: {
    color: '#7a9',
    fontSize: 11,
  },
  value: {
    color: '#cdd',
    fontFamily: 'monospace',
    fontSize: 11,
  },
  abortBtn: {
    width: '100%',
    padding: '5px 0',
    background: '#e4432a',
    color: '#fff',
    border: 'none',
    borderRadius: 5,
    cursor: 'pointer',
    fontWeight: 700,
    fontSize: 11,
    letterSpacing: 1,
  },
};
