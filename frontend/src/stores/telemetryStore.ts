/**
 * 遥测数据状态管理（Zustand Store）。
 *
 * 职责边界：
 * - 管理遥测数据全局状态
 * - 提供 UI 订阅接口
 * - 处理数据更新逻辑
 */

import { create } from 'zustand';
import type {
  Attitude,
  Battery,
  Position,
  SystemStatus,
  TelemetryMessage,
} from '../types/telemetry';

/**
 * 遥测状态接口
 */
interface TelemetryState {
  // 数据状态
  attitude: Attitude | null;
  position: Position | null;
  battery: Battery | null;
  systemStatus: SystemStatus | null;

  // 元数据
  lastUpdateTime: number;
  messageCount: number;

  // 操作方法
  updateTelemetry: (message: TelemetryMessage) => void;
  reset: () => void;
}

/**
 * 创建遥测数据 Store
 */
export const useTelemetryStore = create<TelemetryState>((set) => ({
  // 初始状态
  attitude: null,
  position: null,
  battery: null,
  systemStatus: null,
  lastUpdateTime: 0,
  messageCount: 0,

  /**
   * 更新遥测数据
   */
  updateTelemetry: (message: TelemetryMessage) => {
    set((state) => ({
      // 更新数据字段
      attitude: message.payload.attitude || state.attitude,
      position: message.payload.position || state.position,
      battery: message.payload.battery || state.battery,
      systemStatus: message.payload.system || state.systemStatus,

      // 更新元数据
      lastUpdateTime: message.timestamp * 1000, // 转换为毫秒
      messageCount: state.messageCount + 1,
    }));
  },

  /**
   * 重置状态
   */
  reset: () => {
    set({
      attitude: null,
      position: null,
      battery: null,
      systemStatus: null,
      lastUpdateTime: 0,
      messageCount: 0,
    });
  },
}));
