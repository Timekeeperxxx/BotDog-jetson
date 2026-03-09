/**
 * 急停按钮组件。
 *
 * 职责边界：
 * - 提供急停按钮
 * - 绑定到急停 API
 * - 显示急停状态
 */

import { useState } from "react";
import { useTelemetryStore } from "../stores/telemetryStore";
import { getApiUrl } from "../config/api";

/**
 * 急停按钮组件
 */
export function EmergencyStopButton() {
  const [isStopping, setIsStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const systemStatus = useTelemetryStore((state) => state.systemStatus);

  /**
   * 触发急停
   */
  const handleEmergencyStop = async () => {
    if (!confirm("确认触发紧急制动？")) {
      return;
    }

    setIsStopping(true);
    setError(null);

    try {
      const response = await fetch(getApiUrl("/api/v1/control/e-stop"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.success) {
        console.log("紧急制动已触发");
      } else {
        setError("急停触发失败");
      }
    } catch (err) {
      setError(`急停请求失败: ${err}`);
    } finally {
      setIsStopping(false);
    }
  };

  /**
   * 判断是否处于急停状态
   */
  const isEStopped = systemStatus?.mode === "E_STOP_TRIGGERED";

  return (
    <div className="emergency-stop-container">
      <button
        className={`emergency-stop-button ${isEStopped ? "triggered" : ""} ${
          isStopping ? "stopping" : ""
        }`}
        onClick={handleEmergencyStop}
        disabled={isStopping || isEStopped}
      >
        {isStopping ? "触发中..." : isEStopped ? "紧急制动已触发" : "紧急制动 (E-STOP)"}
      </button>

      {error && (
        <div className="error-message">
          错误: {error}
        </div>
      )}

      {isEStopped && (
        <div className="estop-warning">
          ⚠️ 系统处于紧急制动状态，控制指令已禁用
        </div>
      )}
    </div>
  );
}
