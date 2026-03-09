/**
 * 实时抓拍列表组件
 * 显示 AI 检测到的异常事件
 */

import { useEffect, useState } from 'react';
import { useEventWebSocket } from '../hooks/useEventWebSocket';
import { AlertEvent } from '../types/event';

interface SnapshotListProps {
  maxItems?: number;
  autoScroll?: boolean;
}

export function SnapshotList({
  maxItems = 20,
  autoScroll = true,
}: SnapshotListProps) {
  const { status, alerts, connect, disconnect, clearAlerts } = useEventWebSocket();

  useEffect(() => {
    // 自动连接
    connect();

    return () => {
      disconnect();
    };
  }, []);

  // 显示的告警列表（限制数量）
  const displayAlerts = alerts.slice(0, maxItems);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'CRITICAL':
        return '#ef4444';
      case 'WARNING':
        return '#f59e0b';
      case 'INFO':
        return '#3b82f6';
      default:
        return '#64748b';
    }
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'CRITICAL':
        return '🚨';
      case 'WARNING':
        return '⚠️';
      case 'INFO':
        return 'ℹ️';
      default:
        return '📌';
    }
  };

  return (
    <div
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        background: 'rgba(26, 29, 35, 0.9)',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        borderRadius: '8px',
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <h3
          style={{
            fontSize: '10px',
            fontWeight: 'bold',
            color: '#94a3b8',
            textTransform: 'uppercase',
            letterSpacing: '2px',
            margin: 0,
          }}
        >
          实时抓拍
        </h3>
        <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
          {/* 连接状态指示器 */}
          <div
            style={{
              fontSize: '9px',
              color: status.status === 'connected' ? '#10b981' : '#64748b',
              fontWeight: 'bold',
            }}
          >
            {status.status === 'connected' ? '● 已连接' : '○ 未连接'}
          </div>

          {/* 清空按钮 */}
          {alerts.length > 0 && (
            <button
              onClick={clearAlerts}
              style={{
                background: 'rgba(255, 255, 255, 0.05)',
                color: '#64748b',
                border: 'none',
                borderRadius: '4px',
                padding: '4px 8px',
                fontSize: '9px',
                fontWeight: 'bold',
                cursor: 'pointer',
                textTransform: 'uppercase',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
              }}
            >
              清空
            </button>
          )}
        </div>
      </div>

      {/* 告警列表 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        {displayAlerts.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              color: '#64748b',
              fontSize: '10px',
              padding: '20px',
            }}
          >
            {status.status === 'connecting'
              ? '正在连接...'
              : status.status === 'connected'
              ? '等待识别事件...'
              : '连接已断开'}
          </div>
        ) : (
          displayAlerts.map((alert, index) => (
            <div
              key={`${alert.timestamp}-${index}`}
              style={{
                background: 'rgba(255, 255, 255, 0.02)',
                border: '1px solid rgba(255, 255, 255, 0.05)',
                borderLeft: `3px solid ${getSeverityColor(alert.severity)}`,
                padding: '10px',
                borderRadius: '6px',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
                transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)';
              }}
            >
              {/* 图标 */}
              <div
                style={{
                  fontSize: '24px',
                  opacity: 0.6,
                  flexShrink: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  background: 'rgba(0, 0, 0, 0.3)',
                }}
              >
                {alert.image_url ? (
                  <img
                    src={alert.image_url}
                    alt="snapshot"
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'cover',
                      borderRadius: '50%',
                    }}
                  />
                ) : (
                  getSeverityIcon(alert.severity)
                )}
              </div>

              {/* 内容 */}
              <div
                style={{
                  minWidth: 0,
                  flex: 1,
                }}
              >
                <div
                  style={{
                    fontSize: '10px',
                    fontWeight: 'bold',
                    color: '#cbd5e1',
                    marginBottom: '2px',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {alert.message}
                </div>
                <div
                  style={{
                    fontSize: '8px',
                    color: '#64748b',
                    fontFamily: '"JetBrains Mono", monospace',
                  }}
                >
                  {alert.event_code} •{' '}
                  {new Date(alert.timestamp).toLocaleTimeString('zh-CN', {
                    hour12: false,
                  })}
                  {alert.confidence !== undefined && (
                    <> • 置信度: {alert.confidence.toFixed(1)}%</>
                  )}
                </div>
                {alert.gps && (
                  <div
                    style={{
                      fontSize: '8px',
                      color: '#64748b',
                      fontFamily: '"JetBrains Mono", monospace',
                    }}
                  >
                    📍 {alert.gps.lat.toFixed(4)}, {alert.gps.lon.toFixed(4)}
                  </div>
                )}
              </div>

              {/* 严重程度标签 */}
              <div
                style={{
                  fontSize: '8px',
                  fontWeight: 'bold',
                  color: getSeverityColor(alert.severity),
                  textTransform: 'uppercase',
                  padding: '2px 6px',
                  borderRadius: '4px',
                  background: `${getSeverityColor(
                    alert.severity,
                  )}20`,
                  flexShrink: 0,
                }}
              >
                {alert.severity.toLowerCase()}
              </div>
            </div>
          ))
        )}
      </div>

      {/* 底部统计 */}
      {alerts.length > 0 && (
        <div
          style={{
            padding: '8px 16px',
            borderTop: '1px solid rgba(255, 255, 255, 0.05)',
            fontSize: '9px',
            color: '#64748b',
            textAlign: 'center',
          }}
        >
          共 {alerts.length} 条记录
          {alerts.length > maxItems && ` (显示最近 ${maxItems} 条)`}
        </div>
      )}
    </div>
  );
}
