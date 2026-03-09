/**
 * 遥测数据类型定义。
 *
 * 职责边界：
 * - 定义与后端 WebSocket 协议一致的类型结构
 * - 提供类型安全的数据访问
 */

/**
 * 姿态数据
 */
export interface Attitude {
  pitch: number; // 俯仰角（度）
  roll: number;  // 横滚角（度）
  yaw: number;   // 偏航角（度）
}

/**
 * 位置数据
 */
export interface Position {
  lat: number;  // 纬度（度）
  lon: number;  // 经度（度）
  alt: number;  // 高度（米）
  hdg: number;  // 航向角（度）
}

/**
 * 电池状态
 */
export interface Battery {
  voltage: number;         // 电压（伏特）
  remaining_pct: number;   // 剩余电量百分比（0-100）
}

/**
 * 系统状态
 */
export interface SystemStatus {
  armed: boolean;          // 是否已解锁
  mode: string;            // 飞行模式
  connected: boolean;      // MAVLink 链路是否连通
}

/**
 * 遥测数据载荷
 */
export interface TelemetryPayload {
  attitude?: Attitude;
  position?: Position;
  battery?: Battery;
  system?: SystemStatus;
}

/**
 * WebSocket 消息信封
 */
export interface TelemetryMessage {
  timestamp: number;              // Unix 时间戳（秒）
  msg_type: string;               // 消息类型
  seq: number;                    // 序列号
  source: string;                 // 消息来源
  payload: TelemetryPayload;      // 业务数据载荷
}

/**
 * 系统健康状态
 */
export interface SystemHealth {
  status: "healthy" | "degraded" | "offline";
  mavlink_connected: boolean;
  uptime: number;
}

/**
 * 手动控制指令
 */
export interface ManualControl {
  x: number; // 前进/后退 (-1000~1000)
  y: number; // 左右平移 (-1000~1000)
  z: number; // 上下控制 (-1000~1000)
  r: number; // 偏航转向 (-1000~1000)
}

/**
 * 控制指令确认
 */
export interface ControlAck {
  ack_cmd: string; // 确认的指令类型
  result: "ACCEPTED" | "REJECTED_LOW_BATTERY" | "REJECTED_E_STOP" | "RATE_LIMITED" | "REJECTED_INVALID";
  latency_ms: number; // 处理延迟（毫秒）
}

/**
 * WebSocket 控制消息信封
 */
export interface ControlMessage {
  timestamp: number;
  msg_type: string;
  payload?: ControlAck;
}
