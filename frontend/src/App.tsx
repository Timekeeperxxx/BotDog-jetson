/**
 * 主应用组件。
 *
 * 职责边界：
 * - 整合所有子组件
 * - 管理 WebSocket 连接
 * - 协调状态更新
 */

import { useEffect } from "react";
import { useTelemetryWebSocket } from "./hooks/useTelemetryWebSocket";
import { useTelemetryStore } from "./stores/telemetryStore";
import { AttitudeHUD } from "./components/AttitudeHUD";
import { PositionPanel } from "./components/PositionPanel";
import { BatteryIndicator } from "./components/BatteryIndicator";
import { StatusBar } from "./components/StatusBar";
import { ControlPanel } from "./components/ControlPanel";
import { EmergencyStopButton } from "./components/EmergencyStopButton";
import { VideoPlayer } from "./components/VideoPlayer";

// 立即检查环境变量（应用启动时）
// console.log('🚀 [App] 应用启动');
// console.log('🔧 [App] 环境变量 VITE_API_BASE_URL:', import.meta.env.VITE_API_BASE_URL);

/**
 * 主应用组件
 */
function App() {
  const { message, status, error, reconnect } = useTelemetryWebSocket();
  const updateTelemetry = useTelemetryStore((state) => state.updateTelemetry);

  /**
   * 监听消息更新，同步到 Store
   */
  useEffect(() => {
    if (message) {
      updateTelemetry(message);
    }
  }, [message, updateTelemetry]);

  return (
    <div className="app">
      {/* 状态栏 */}
      <StatusBar connectionStatus={status} error={error} onReconnect={reconnect} />

      {/* 主内容区 */}
      <main className="main-content">
        {/* 标题 */}
        <header className="app-header">
          <h1>BotDog 智能巡检系统</h1>
          <p className="subtitle">阶段 3 - 媒体管线与 WebRTC 流</p>
        </header>

        {/* 视频播放器 */}
        <div className="video-section">
          <VideoPlayer />
        </div>

        {/* 遥测数据面板 */}
        <div className="telemetry-grid">
          {/* 姿态 HUD */}
          <div className="panel">
            <AttitudeHUD />
          </div>

          {/* 位置信息 */}
          <div className="panel">
            <PositionPanel />
          </div>

          {/* 控制面板 */}
          <div className="panel">
            <ControlPanel />
          </div>

          {/* 急停按钮 */}
          <div className="panel">
            <EmergencyStopButton />
          </div>
        </div>

        {/* 底部信息栏 */}
        <footer className="app-footer">
          <div className="footer-section">
            <BatteryIndicator />
          </div>
        </footer>
      </main>
    </div>
  );
}

export default App;
