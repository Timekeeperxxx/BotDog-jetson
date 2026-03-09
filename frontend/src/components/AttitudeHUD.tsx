/**
 * HUD 姿态仪表组件。
 *
 * 职责边界：
 * - 显示姿态数据（俯仰、横滚、偏航）
 * - 实时更新姿态指示器
 * - 提供可视化反馈
 */

import { useTelemetryStore } from "../stores/telemetryStore";
import type { Attitude } from "../types/telemetry";

/**
 * 姿态指示器组件
 */
function AttitudeIndicator({ attitude }: { attitude: Attitude }) {
  const { pitch, roll, yaw } = attitude;

  return (
    <div className="attitude-indicator">
      <svg width="200" height="200" viewBox="0 0 200 200">
        {/* 外圆 */}
        <circle
          cx="100"
          cy="100"
          r="90"
          fill="none"
          stroke="#4ade80"
          strokeWidth="2"
        />

        {/* 俯仰角指示（竖线） */}
        <line
          x1="100"
          y1="100"
          x2="100"
          y2={100 - pitch * 50}
          stroke="#f87171"
          strokeWidth="3"
        />

        {/* 横滚角指示（横线） */}
        <line
          x1="100"
          y1="100"
          x2={100 + roll * 50}
          y2="100"
          stroke="#60a5fa"
          strokeWidth="3"
        />

        {/* 偏航角指示（箭头） */}
        <polygon
          points={`100,10 ${110 - yaw * 0.5},30 ${90 + yaw * 0.5},30`}
          fill="#fbbf24"
        />

        {/* 中心点 */}
        <circle cx="100" cy="100" r="3" fill="#ffffff" />
      </svg>
    </div>
  );
}

/**
 * 姿态数值显示
 */
function AttitudeValues({ attitude }: { attitude: Attitude }) {
  const { pitch, roll, yaw } = attitude;

  return (
    <div className="attitude-values">
      <div className="value-item">
        <span className="label">俯仰</span>
        <span className="value">{pitch.toFixed(1)}°</span>
      </div>
      <div className="value-item">
        <span className="label">横滚</span>
        <span className="value">{roll.toFixed(1)}°</span>
      </div>
      <div className="value-item">
        <span className="label">偏航</span>
        <span className="value">{yaw.toFixed(1)}°</span>
      </div>
    </div>
  );
}

/**
 * HUD 姿态组件主函数
 */
export function AttitudeHUD() {
  const attitude = useTelemetryStore((state) => state.attitude);

  // 无数据时显示占位
  if (!attitude) {
    return (
      <div className="attitude-hud placeholder">
        <div className="placeholder-text">等待姿态数据...</div>
      </div>
    );
  }

  return (
    <div className="attitude-hud">
      <div className="hud-title">姿态仪</div>
      <AttitudeIndicator attitude={attitude} />
      <AttitudeValues attitude={attitude} />
    </div>
  );
}
