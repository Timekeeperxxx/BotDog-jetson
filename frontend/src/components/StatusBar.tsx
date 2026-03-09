/**
 * 系统状态栏组件。
 *
 * 职责边界：
 * - 显示 WebSocket 连接状态
 * - 显示系统模式和解锁状态
 * - 显示消息统计信息
 */

import { useTelemetryStore } from "../stores/telemetryStore";
import type { ConnectionStatus } from "../hooks/useTelemetryWebSocket";

interface StatusBarProps {
  connectionStatus: ConnectionStatus;
  error: string | null;
  onReconnect: () => void;
}

/**
 * 状态栏组件
 */
export function StatusBar({ connectionStatus, error, onReconnect }: StatusBarProps) {
  const systemStatus = useTelemetryStore((state) => state.systemStatus);
  const messageCount = useTelemetryStore((state) => state.messageCount);
  const lastUpdateTime = useTelemetryStore((state) => state.lastUpdateTime);

  /**
   * 获取连接状态显示文本
   */
  const getConnectionText = () => {
    switch (connectionStatus) {
      case "connecting":
        return "连接中...";
      case "connected":
        return "已连接";
      case "disconnected":
        return "未连接";
      case "error":
        return "连接错误";
      default:
        return "未知状态";
    }
  };

  /**
   * 获取连接状态颜色类
   */
  const getConnectionClass = () => {
    switch (connectionStatus) {
      case "connected":
        return "status-connected";
      case "connecting":
        return "status-connecting";
      case "error":
        return "status-error";
      default:
        return "status-disconnected";
    }
  };

  return (
    <div className="status-bar">
      {/* 左侧：连接状态 */}
      <div className="status-section">
        <span className="status-label">WebSocket:</span>
        <span className={`status-value ${getConnectionClass()}`}>
          {getConnectionText()}
        </span>

        {(connectionStatus === "disconnected" || connectionStatus === "error") && (
          <button className="reconnect-button" onClick={onReconnect}>
            重连
          </button>
        )}
      </div>

      {/* 中间：系统状态 */}
      <div className="status-section">
        <span className="status-label">系统模式:</span>
        <span className="status-value">
          {systemStatus?.mode || "--"}
        </span>

        <span className="status-label">解锁:</span>
        <span className={`status-value ${systemStatus?.armed ? "armed" : "disarmed"}`}>
          {systemStatus?.armed ? "是" : "否"}
        </span>
      </div>

      {/* 右侧：统计信息 */}
      <div className="status-section">
        <span className="status-label">消息数:</span>
        <span className="status-value">{messageCount}</span>

        <span className="status-label">最后更新:</span>
        <span className="status-value">
          {lastUpdateTime > 0
            ? new Date(lastUpdateTime).toLocaleTimeString()
            : "--"}
        </span>
      </div>

      {/* 错误信息 */}
      {error && (
        <div className="error-message">
          错误: {error}
        </div>
      )}
    </div>
  );
}
