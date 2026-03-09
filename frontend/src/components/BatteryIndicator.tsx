/**
 * 电池状态显示组件。
 *
 * 职责边界：
 * - 显示电池电压和剩余电量
 * - 提供可视化电量指示器
 * - 低电量时显示警告
 */

import { useTelemetryStore } from "../stores/telemetryStore";

/**
 * 电池状态组件
 */
export function BatteryIndicator() {
  const battery = useTelemetryStore((state) => state.battery);

  // 无数据时显示占位
  if (!battery) {
    return (
      <div className="battery-indicator placeholder">
        <div className="placeholder-text">--%</div>
      </div>
    );
  }

  const { voltage, remaining_pct } = battery;

  // 判断电量状态
  const getBatteryStatus = (pct: number) => {
    if (pct > 50) return "good";
    if (pct > 20) return "warning";
    return "critical";
  };

  const status = getBatteryStatus(remaining_pct);

  return (
    <div className={`battery-indicator ${status}`}>
      <div className="battery-text">
        <span className="voltage">{voltage.toFixed(1)}V</span>
        <span className="percentage">{remaining_pct}%</span>
      </div>

      {/* 可视化电量条 */}
      <div className="battery-bar">
        <div
          className="battery-fill"
          style={{ width: `${remaining_pct}%` }}
        />
      </div>
    </div>
  );
}
