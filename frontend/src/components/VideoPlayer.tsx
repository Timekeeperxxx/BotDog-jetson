/**
 * 视频播放器组件。
 *
 * 职责边界：
 * - 显示实时视频流
 * - 显示视频流状态
 * - 处理全屏控制
 * - 叠加 HUD 数据
 */

import { useEffect } from "react";
import { useWebRTC } from "../hooks/useWebRTC";
import { useTelemetryStore } from "../stores/telemetryStore";

/**
 * HUD 组件 - 叠加在视频上的数据显示
 */
function HUDOverlay() {
  const attitude = useTelemetryStore((state) => state.attitude);
  const position = useTelemetryStore((state) => state.position);
  const battery = useTelemetryStore((state) => state.battery);

  return (
    <div className="hud-overlay">
      {/* 左上角 - 姿态信息 */}
      <div className="hud-panel hud-top-left">
        <div className="hud-title">姿态</div>
        {attitude ? (
          <div className="hud-values">
            <div className="hud-item">
              <span className="hud-label">俯仰:</span>
              <span className="hud-value">{attitude.pitch.toFixed(1)}°</span>
            </div>
            <div className="hud-item">
              <span className="hud-label">横滚:</span>
              <span className="hud-value">{attitude.roll.toFixed(1)}°</span>
            </div>
            <div className="hud-item">
              <span className="hud-label">航向:</span>
              <span className="hud-value">{attitude.yaw.toFixed(1)}°</span>
            </div>
          </div>
        ) : (
          <div className="hud-placeholder">等待数据...</div>
        )}
      </div>

      {/* 右上角 - 位置信息 */}
      <div className="hud-panel hud-top-right">
        <div className="hud-title">位置</div>
        {position ? (
          <div className="hud-values">
            <div className="hud-item">
              <span className="hud-label">纬度:</span>
              <span className="hud-value">{position.lat.toFixed(6)}°</span>
            </div>
            <div className="hud-item">
              <span className="hud-label">经度:</span>
              <span className="hud-value">{position.lon.toFixed(6)}°</span>
            </div>
            <div className="hud-item">
              <span className="hud-label">高度:</span>
              <span className="hud-value">{position.alt.toFixed(1)}m</span>
            </div>
            <div className="hud-item">
              <span className="hud-label">航向:</span>
              <span className="hud-value">{position.hdg.toFixed(1)}°</span>
            </div>
          </div>
        ) : (
          <div className="hud-placeholder">等待数据...</div>
        )}
      </div>

      {/* 左下角 - 电池状态 */}
      <div className="hud-panel hud-bottom-left">
        <div className="hud-title">电池</div>
        {battery ? (
          <div className="hud-values">
            <div className="hud-item">
              <span className="hud-label">电压:</span>
              <span className="hud-value">{battery.voltage.toFixed(1)}V</span>
            </div>
            <div className="hud-item">
              <span className="hud-label">电量:</span>
              <span className={`hud-value ${battery.remaining_pct < 20 ? 'hud-critical' : battery.remaining_pct < 50 ? 'hud-warning' : 'hud-good'}`}>
                {battery.remaining_pct.toFixed(0)}%
              </span>
            </div>
          </div>
        ) : (
          <div className="hud-placeholder">等待数据...</div>
        )}
      </div>

      {/* 中心十字准星 */}
      <div className="hud-crosshair">
        <div className="crosshair-vertical"></div>
        <div className="crosshair-horizontal"></div>
        <div className="crosshair-center"></div>
      </div>
    </div>
  );
}

/**
 * 视频播放器组件
 */
export function VideoPlayer() {
  const { status, error, clientId, videoRef, connect, disconnect } = useWebRTC();

  /**
   * 组件挂载时自动连接
   */
  useEffect(() => {
    connect();
    return () => {
      disconnect();
    };
  }, [connect, disconnect]);

  /**
   * 获取状态显示文本
   */
  const getStatusText = (): string => {
    switch (status) {
      case "connecting":
        return "连接中...";
      case "connected":
        return "已连接";
      case "disconnected":
        return "未连接";
      case "error":
        return "连接错误";
    }
  };

  /**
   * 获取状态样式类
   */
  const getStatusClass = (): string => {
    switch (status) {
      case "connecting":
        return "status-connecting";
      case "connected":
        return "status-connected";
      case "disconnected":
        return "status-disconnected";
      case "error":
        return "status-error";
    }
  };

  return (
    <div className="video-player-container">
      {/* 视频播放器 */}
      <div className="video-wrapper">
        <video
          ref={videoRef}
          className="video-element"
          autoPlay
          playsInline
          muted
        />

        {/* HUD 叠层 */}
        {status === "connected" && <HUDOverlay />}

        {/* 加载/错误提示 */}
        {status !== "connected" && (
          <div className="video-status-overlay">
            <div className="status-icon">
              {status === "connecting" && "⟳"}
              {status === "disconnected" && "○"}
              {status === "error" && "!"}
            </div>
            <div className="status-text">{getStatusText()}</div>
            {error && <div className="error-text">{error}</div>}
            {status === "disconnected" && (
              <button className="reconnect-button" onClick={connect}>
                重新连接
              </button>
            )}
          </div>
        )}
      </div>

      {/* 控制栏 */}
      <div className="video-controls">
        <div className="control-item">
          <span className="control-label">状态:</span>
          <span className={`control-value ${getStatusClass()}`}>
            {getStatusText()}
          </span>
        </div>
        {clientId && (
          <div className="control-item">
            <span className="control-label">客户端 ID:</span>
            <span className="control-value">{clientId.slice(0, 8)}...</span>
          </div>
        )}
        <div className="control-item control-item-right">
          <button
            className="control-button"
            onClick={status === "connected" ? disconnect : connect}
          >
            {status === "connected" ? "断开" : "连接"}
          </button>
        </div>
      </div>
    </div>
  );
}
