/**
 * 位置数据显示组件。
 *
 * 职责边界：
 * - 显示 GPS 位置和航向信息
 * - 提供结构化位置信息展示
 */

import { useTelemetryStore } from "../stores/telemetryStore";

/**
 * 位置面板组件
 */
export function PositionPanel() {
  const position = useTelemetryStore((state) => state.position);

  // 无数据时显示占位
  if (!position) {
    return (
      <div className="position-panel placeholder">
        <div className="panel-title">位置信息</div>
        <div className="placeholder-text">等待位置数据...</div>
      </div>
    );
  }

  return (
    <div className="position-panel">
      <div className="panel-title">位置信息</div>
      <div className="position-grid">
        <div className="grid-item">
          <span className="label">纬度</span>
          <span className="value">{position.lat.toFixed(7)}</span>
        </div>
        <div className="grid-item">
          <span className="label">经度</span>
          <span className="value">{position.lon.toFixed(7)}</span>
        </div>
        <div className="grid-item">
          <span className="label">高度</span>
          <span className="value">{position.alt.toFixed(1)} m</span>
        </div>
        <div className="grid-item">
          <span className="label">航向</span>
          <span className="value">{position.hdg.toFixed(1)}°</span>
        </div>
      </div>
    </div>
  );
}
