/**
 * 真实的WebSocket连接管理 - 替换模拟数据
 * 连接到后端的实际WebSocket端点
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { getWsUrl, getApiUrl } from '../config/api';

// ==================== 类型定义 ====================
export interface TelemetryData {
  timestamp: number;
  latency_ms: number | null;
  rssi_dbm: number | null;
  core_temp_c: number | null;
  battery_pct: number | null;
  attitude: {
    pitch: number;
    roll: number;
    yaw: number;
  };
  position: {
    groundspeed: number | null;
    lat: number | null;
    lon: number | null;
    alt: number | null;
  };
  motors: Array<{
    name: string;
    temp_c: number;
    current_a: number;
    load_pct: number;
  }>;
}

export interface SnapshotData {
  id: string;
  confidence: number;
  created_at: number;
  event_type: string;
  thumbnail_url?: string;
}

export interface LogEntry {
  timestamp: number;
  level: 'info' | 'warning' | 'error';
  module: string;
  message: string;
}

export interface SystemStatus {
  status: 'DISCONNECTED' | 'STANDBY' | 'IN_MISSION' | 'E_STOP_TRIGGERED';
  uptime: string;
}

// ==================== WebSocket连接Hook ====================
export function useBotDogWebSocket() {
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  // setSnapshots 暂留但不调用——等待后端实现抓拍功能
  const [snapshots, _setSnapshots] = useState<SnapshotData[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus>({
    status: 'DISCONNECTED',
    uptime: '00:00:00',
  });
  const [isConnected, setIsConnected] = useState(false);
  const [lastTelemetryAt, setLastTelemetryAt] = useState<number | null>(null);
  const [telemetryStale, setTelemetryStale] = useState(false);

  const telemetryWsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const startTimeRef = useRef<number>(Date.now());
  const connectionIdRef = useRef(0); // 连接实例ID，防止旧连接回调干扰
  // Ref 版 lastTelemetryAt，供 stale 检测 interval 使用（避免 stale closure）
  const lastTelemetryAtRef = useRef<number | null>(null);

  // 连接WebSocket
  const connect = useCallback(() => {
    const rs = telemetryWsRef.current?.readyState;
    if (rs === WebSocket.OPEN || rs === WebSocket.CONNECTING) {
      console.log('WebSocket已连接或正在连接，跳过重复连接');
      return;
    }

    // 关闭处于 CLOSING 状态的旧连接
    if (telemetryWsRef.current && telemetryWsRef.current.readyState !== WebSocket.CLOSED) {
      console.log('关闭旧WebSocket连接');
      telemetryWsRef.current.close(1000);
      telemetryWsRef.current = null;
    }

    // 清除之前的重连定时器
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    // 增加连接ID
    connectionIdRef.current += 1;
    const currentConnectionId = connectionIdRef.current;

    try {
      console.log('正在连接WebSocket:', getWsUrl('/ws/telemetry'));
      const ws = new WebSocket(getWsUrl('/ws/telemetry'));
      telemetryWsRef.current = ws;

      ws.onopen = () => {
        if (currentConnectionId !== connectionIdRef.current) {
          console.log('忽略旧连接的onopen回调');
          return;
        }
        console.log(`✅ WebSocket连接成功 (ID: ${currentConnectionId})`);
        setIsConnected(true);
        setSystemStatus(prev => ({ ...prev, status: 'STANDBY' }));
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (currentConnectionId !== connectionIdRef.current) {
          console.log('忽略旧连接的消息');
          return;
        }

        try {
          const message = JSON.parse(event.data) as Record<string, unknown>;

          if (message.msg_type === 'TELEMETRY_UPDATE') {
            const payload = message.payload as Record<string, unknown>;

            // 记录本次遥测时间，无论字段是否完整
            const now = Date.now();
            lastTelemetryAtRef.current = now;
            setLastTelemetryAt(now);
            setTelemetryStale(false);

            // 按字段类型提取，缺失时使用 null 或安全零值（不伪造有意义的假数据）
            const rawBattery = payload.battery as Record<string, unknown> | undefined;
            const rawPosition = payload.position as Record<string, unknown> | undefined;
            const rawAttitude = payload.attitude as { pitch: number; roll: number; yaw: number } | undefined;

            const telemetryData: TelemetryData = {
              timestamp: typeof message.timestamp === 'number'
                ? message.timestamp
                : Date.now() / 1000,
              latency_ms: typeof message.latency_ms === 'number' ? message.latency_ms : null,
              rssi_dbm: typeof message.rssi_dbm === 'number' ? message.rssi_dbm : null,
              core_temp_c: typeof message.core_temp_c === 'number' ? message.core_temp_c : null,
              battery_pct: typeof rawBattery?.remaining_pct === 'number'
                ? rawBattery.remaining_pct as number
                : null,
              attitude: rawAttitude ?? { pitch: 0, roll: 0, yaw: 0 },
              position: {
                groundspeed: typeof rawPosition?.groundspeed === 'number'
                  ? rawPosition.groundspeed as number
                  : null,
                lat: typeof rawPosition?.lat === 'number' ? rawPosition.lat as number : null,
                lon: typeof rawPosition?.lon === 'number' ? rawPosition.lon as number : null,
                alt: typeof rawPosition?.alt === 'number' ? rawPosition.alt as number : null,
              },
              motors: [],
            };

            setTelemetry(telemetryData);

            // 更新系统状态
            const rawSystem = payload.system as { armed?: boolean } | undefined;
            if (rawSystem) {
              const newStatus = rawSystem.armed ? 'IN_MISSION' : 'STANDBY';
              setSystemStatus(prev => ({
                ...prev,
                status: newStatus as SystemStatus['status'],
              }));
            }
          }
        } catch (error) {
          console.error('解析WebSocket消息失败:', error);
        }
      };

      ws.onerror = (error) => {
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        console.error('❌ WebSocket错误:', error);
        setIsConnected(false);
      };

      ws.onclose = (event) => {
        if (currentConnectionId !== connectionIdRef.current) {
          console.log('忽略旧连接的onclose回调');
          return;
        }

        console.log(`WebSocket连接关闭: code=${event.code}, reason=${event.reason || '无'}`);
        setIsConnected(false);
        setSystemStatus(prev => ({ ...prev, status: 'DISCONNECTED' }));

        if (event.code === 1000) {
          console.log('WebSocket正常关闭，不重连');
          return;
        }

        // 指数退避重连：前 10 次加速上升，之后重置计数以 10s 间隔持续重试
        if (reconnectAttemptsRef.current >= 10) {
          reconnectAttemptsRef.current = 0;
          console.log('🔄 WebSocket重连计数已重置，继续以10s间隔持续重试');
        }
        reconnectAttemptsRef.current++;
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 10000);
        console.log(`⏳ 将在 ${delay}ms 后重连 (尝试 ${reconnectAttemptsRef.current})`);

        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, delay);
      };
    } catch (error) {
      console.error('❌ 创建WebSocket连接失败:', error);
      setIsConnected(false);
    }
  }, []);

  // 断开连接
  const disconnect = useCallback(() => {
    connectionIdRef.current += 1;
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (telemetryWsRef.current) {
      telemetryWsRef.current.close(1000);
      telemetryWsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  // 添加日志
  const addLog = useCallback((message: string, level: 'info' | 'warning' | 'error' = 'info', module: string = 'SYSTEM') => {
    const newLog: LogEntry = {
      timestamp: Date.now() / 1000,
      level,
      module,
      message,
    };
    setLogs(prev => [...prev, newLog].slice(-40));
  }, []);

  // 触发急停：调用后端真实接口，systemStatus 由后端 WebSocket 更新，不在前端本地伪造
  const triggerEmergencyStop = useCallback(async () => {
    try {
      const res = await fetch(getApiUrl('/api/v1/control/e-stop'), {
        method: 'POST',
      });
      if (res.ok) {
        addLog('紧急停止已触发', 'error', 'SYSTEM');
      } else {
        addLog('紧急停止请求失败', 'error', 'SYSTEM');
      }
    } catch {
      addLog('紧急停止请求失败', 'error', 'SYSTEM');
    }
  }, [addLog]);

  // 遥测数据新鲜度检测：超过 3s 未收到 TELEMETRY_UPDATE 则标记为 stale
  useEffect(() => {
    const interval = setInterval(() => {
      if (
        lastTelemetryAtRef.current !== null &&
        Date.now() - lastTelemetryAtRef.current > 3000
      ) {
        setTelemetryStale(true);
      }
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // 计算运行时间
  useEffect(() => {
    const interval = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
      const hours = Math.floor(elapsed / 3600).toString().padStart(2, '0');
      const minutes = Math.floor((elapsed % 3600) / 60).toString().padStart(2, '0');
      const seconds = (elapsed % 60).toString().padStart(2, '0');
      setSystemStatus(prev => ({ ...prev, uptime: `${hours}:${minutes}:${seconds}` }));
    }, 1000);

    return () => clearInterval(interval);
  }, []);

  // 组件挂载时连接WebSocket
  useEffect(() => {
    connect();

    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  return {
    // 遥测数据
    telemetry,
    isConnected,
    lastTelemetryAt,
    telemetryStale,
    // 快照列表
    snapshots,
    // 系统日志
    logs,
    addLog,
    // 系统状态
    systemStatus,
    triggerEmergencyStop,
    // 连接控制
    connect,
    disconnect,
  };
}
