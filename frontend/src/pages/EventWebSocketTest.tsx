/**
 * 事件 WebSocket 测试页面
 * 用于测试告警事件的实时接收
 */

import { useState, useEffect } from 'react';
import { getWsUrl } from '../config/api';

export function EventWebSocketTest() {
  const [status, setStatus] = useState<string>('disconnected');
  const [messages, setMessages] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 连接 WebSocket
    const ws = new WebSocket(getWsUrl('/ws/event'));

    ws.onopen = () => {
      console.log('WebSocket 已连接');
      setStatus('connected');
      setError(null);
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        console.log('收到消息:', message);

        setMessages((prev) => [message, ...prev].slice(0, 50));
      } catch (err) {
        console.error('解析消息失败:', err);
      }
    };

    ws.onerror = (err) => {
      console.error('WebSocket 错误:', err);
      setStatus('error');
      setError('连接错误');
    };

    ws.onclose = () => {
      console.log('WebSocket 已关闭');
      setStatus('disconnected');
    };

    return () => {
      ws.close();
    };
  }, []);

  // 发送测试消息
  const sendTestMessage = () => {
    const ws = new WebSocket(getWsUrl('/ws/event'));

    ws.onopen = () => {
      ws.send(JSON.stringify({
        msg_type: 'ping',
        timestamp: new Date().toISOString(),
      }));
    };

    setTimeout(() => ws.close(), 1000);
  };

  return (
    <div
      style={{
        padding: '20px',
        background: '#0f1115',
        color: '#f1f5f9',
        minHeight: '100vh',
      }}
    >
      <div style={{ marginBottom: '24px' }}>
        <h1
          style={{
            fontSize: '24px',
            fontWeight: 'bold',
            marginBottom: '8px',
          }}
        >
          事件 WebSocket 测试
        </h1>
        <p style={{ fontSize: '14px', color: '#64748b', margin: 0 }}>
          测试实时告警事件的接收
        </p>
      </div>

      {/* 状态栏 */}
      <div
        style={{
          background: 'rgba(26, 29, 35, 0.9)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: '8px',
          padding: '16px',
          marginBottom: '20px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div>
            <div
              style={{
                fontSize: '10px',
                fontWeight: 'bold',
                color: '#94a3b8',
                textTransform: 'uppercase',
                marginBottom: '4px',
              }}
            >
              连接状态
            </div>
            <div
              style={{
                fontSize: '14px',
                fontWeight: 'bold',
                color:
                  status === 'connected'
                    ? '#10b981'
                    : status === 'error'
                    ? '#ef4444'
                    : '#64748b',
              }}
            >
              {status === 'connected'
                ? '✅ 已连接'
                : status === 'error'
                ? '❌ 错误'
                : '○ 未连接'}
            </div>
          </div>

          <div>
            <div
              style={{
                fontSize: '10px',
                fontWeight: 'bold',
                color: '#94a3b8',
                textTransform: 'uppercase',
                marginBottom: '4px',
              }}
            >
              消息数量
            </div>
            <div
              style={{
                fontSize: '14px',
                fontWeight: 'bold',
                color: '#e2e8f0',
              }}
            >
              {messages.length}
            </div>
          </div>
        </div>

        <button
          onClick={sendTestMessage}
          style={{
            padding: '10px 20px',
            background: '#3b82f6',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            fontWeight: 'bold',
            fontSize: '12px',
            cursor: 'pointer',
            textTransform: 'uppercase',
          }}
        >
          发送测试消息
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div
          style={{
            padding: '12px',
            marginBottom: '20px',
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '6px',
            color: '#ef4444',
            fontSize: '12px',
          }}
        >
          {error}
        </div>
      )}

      {/* 消息列表 */}
      <div
        style={{
          background: 'rgba(26, 29, 35, 0.9)',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          borderRadius: '8px',
          padding: '16px',
        }}
      >
        <div
          style={{
            marginBottom: '12px',
            fontSize: '12px',
            fontWeight: 'bold',
            color: '#94a3b8',
            textTransform: 'uppercase',
          }}
        >
          消息列表
        </div>

        {messages.length === 0 ? (
          <div
            style={{
              padding: '40px',
              textAlign: 'center',
              color: '#64748b',
              fontSize: '12px',
            }}
          >
            {status === 'connected'
              ? '等待消息...'
              : '等待连接...'}
          </div>
        ) : (
          messages.map((msg, index) => (
            <div
              key={`${msg.timestamp}-${index}`}
              style={{
                padding: '12px',
                marginBottom: '8px',
                background: 'rgba(0, 0, 0, 0.3)',
                border: '1px solid rgba(255, 255, 255, 0.05)',
                borderRadius: '6px',
                fontSize: '11px',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: '4px',
                }}
              >
                <span
                  style={{
                    fontWeight: 'bold',
                    color: '#3b82f6',
                  }}
                >
                  {msg.msg_type}
                </span>
                <span
                  style={{
                    color: '#64748b',
                    fontFamily: '"JetBrains Mono", monospace',
                    fontSize: '10px',
                  }}
                >
                  {new Date(msg.timestamp).toLocaleTimeString('zh-CN', {
                    hour12: false,
                  })}
                </span>
              </div>

              {msg.payload && (
                <pre
                  style={{
                    margin: 0,
                    padding: '8px',
                    background: 'rgba(0, 0, 0, 0.5)',
                    borderRadius: '4px',
                    fontSize: '10px',
                    color: '#cbd5e1',
                    overflow: 'auto',
                  }}
                >
                  {JSON.stringify(msg.payload, null, 2)}
                </pre>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
