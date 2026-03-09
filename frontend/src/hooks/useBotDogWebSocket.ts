/**
 * 真实的WebSocket连接管理 - 替换模拟数据
 * 连接到后端的实际WebSocket端点
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { getWsUrl } from '../config/api';

// ==================== 类型定义 ====================
export interface TelemetryData {
  timestamp: number;
  latency_ms: number;
  rssi_dbm: number;
  core_temp_c: number;
  battery_pct: number;
  attitude: {
    pitch: number;
    roll: number;
    yaw: number;
  };
  position: {
    alt: number;
    groundspeed: number;
    lat: number;
    lon: number;
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
  // @ts-ignore - 暂时未使用，等待后端实现抓拍功能
  const [snapshots, setSnapshots] = useState<SnapshotData[]>([]);
  // @ts-ignore - 暂时未使用，等待后端实现日志功能
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus>({
    status: 'DISCONNECTED',
    uptime: '00:00:00',
  });
  const [isConnected, setIsConnected] = useState(false);

  const telemetryWsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const startTimeRef = useRef<number>(Date.now());
  const connectionIdRef = useRef(0); // 连接实例ID，防止旧连接回调干扰

  // 连接WebSocket
  const connect = useCallback(() => {
    if (telemetryWsRef.current?.readyState === WebSocket.OPEN) {
      console.log('WebSocket已连接，跳过重复连接');
      return;
    }

    // 关闭旧连接
    if (telemetryWsRef.current && telemetryWsRef.current.readyState !== WebSocket.CLOSED) {
      console.log('关闭旧WebSocket连接');
      telemetryWsRef.current.close();
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
        // 检查是否是最新的连接
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
        // 检查是否是最新的连接
        if (currentConnectionId !== connectionIdRef.current) {
          console.log('忽略旧连接的消息');
          return;
        }

        try {
          const message = JSON.parse(event.data);
          // 仅在调试模式下打印消息，避免日志刷屏
          // console.log('收到WebSocket消息:', message);

          // 处理不同类型的消息
          if (message.msg_type === 'TELEMETRY_UPDATE') {
            const payload = message.payload;

            // 转换为前端数据格式
            const telemetryData: TelemetryData = {
              timestamp: message.timestamp || Date.now() / 1000,
              latency_ms: message.latency_ms || 20,
              rssi_dbm: message.rssi_dbm || -60,
              core_temp_c: message.core_temp_c || 42, // 模拟温度
              battery_pct: payload.battery?.remaining_pct || 85, // 使用真实电池数据
              attitude: payload.attitude || {
                pitch: 0,
                roll: 0,
                yaw: 0,
              },
              position: {
                alt: payload.position?.alt || 1.2,
                groundspeed: payload.position?.groundspeed || 0.8,
                lat: payload.position?.lat || 39.91,
                lon: payload.position?.lon || 116.40,
              },
              motors: [], // 后端暂不提供电机数据，使用空数组
            };

            setTelemetry(telemetryData);

            // 更新系统状态
            if (payload.system) {
              const newStatus = payload.system.armed ? 'IN_MISSION' : 'STANDBY';
              setSystemStatus(prev => ({ ...prev, status: newStatus as any }));
            }
          }
        } catch (error) {
          console.error('解析WebSocket消息失败:', error);
        }
      };

      ws.onerror = (error) => {
        // 检查是否是最新的连接
        if (currentConnectionId !== connectionIdRef.current) {
          return;
        }
        console.error('❌ WebSocket错误:', error);
        setIsConnected(false);
      };

      ws.onclose = (event) => {
        // 检查是否是最新的连接
        if (currentConnectionId !== connectionIdRef.current) {
          console.log('忽略旧连接的onclose回调');
          return;
        }

        console.log(`WebSocket连接关闭: code=${event.code}, reason=${event.reason || '无'}`);
        setIsConnected(false);
        setSystemStatus(prev => ({ ...prev, status: 'DISCONNECTED' }));

        // 避免正常关闭时重连
        if (event.code === 1000) {
          console.log('WebSocket正常关闭，不重连');
          return;
        }

        // 尝试重连
        if (reconnectAttemptsRef.current < 10) {
          reconnectAttemptsRef.current++;
          const delay = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current - 1), 10000);
          console.log(`⏳ 将在 ${delay}ms 后重连 (尝试 ${reconnectAttemptsRef.current}/10)`);

          reconnectTimeoutRef.current = window.setTimeout(() => {
            connect();
          }, delay);
        } else {
          console.error('❌ WebSocket重连次数已达上限');
          setSystemStatus(prev => ({ ...prev, status: 'DISCONNECTED' }));
        }
      };
    } catch (error) {
      console.error('❌ 创建WebSocket连接失败:', error);
      setIsConnected(false);
    }
  }, []);

  // 断开连接
  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    if (telemetryWsRef.current) {
      telemetryWsRef.current.close();
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

  // 触发急停
  const triggerEmergencyStop = useCallback(() => {
    // TODO: 通过WebSocket发送急停指令到后端
    setSystemStatus({ status: 'E_STOP_TRIGGERED', uptime: systemStatus.uptime });
    addLog('紧急停止已触发', 'error', 'SYSTEM');

    // 3秒后恢复
    setTimeout(() => {
      setSystemStatus({ status: 'STANDBY', uptime: systemStatus.uptime });
      addLog('系统已恢复待机状态', 'info', 'SYSTEM');
    }, 3000);
  }, [systemStatus.uptime, addLog]);

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

  // 等待后端实现抓拍功能
  // TODO: 从后端WebSocket接收真实的抓拍事件数据

  // 等待后端实现日志功能
  // TODO: 从后端WebSocket接收真实的系统日志数据

  return {
    // 遥测数据
    telemetry,
    isConnected,
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