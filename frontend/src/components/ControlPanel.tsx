/**
 * 控制输入面板组件。
 *
 * 职责边界：
 * - 监听键盘输入（WASD + 方向键）
 * - 10Hz 采样控制输入
 * - 发送 MANUAL_CONTROL 指令
 * - 显示控制状态和反馈
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useControlWebSocket } from "../hooks/useControlWebSocket";
import { useGamepad } from "../hooks/useGamepad";
import { mapGamepadToControl } from "../utils/gamepadUtils";
import type { ManualControl } from "../types/telemetry";

/**
 * 控制输入面板组件
 */
export function ControlPanel() {
  const { status, lastAck, sendControl, reconnect, isRateLimited } =
    useControlWebSocket();

  // 游戏手柄 Hook
  const gamepad = useGamepad(0);

  const [controlInput, setControlInput] = useState<ManualControl>({
    x: 0,
    y: 0,
    z: 0,
    r: 0,
  });
  const [isArmed, setIsArmed] = useState(false);

  const keysPressedRef = useRef<Set<string>>(new Set());
  const controlLoopRef = useRef<number | null>(null);

  /**
   * 键盘映射
   */
  const KEY_MAP: Record<string, keyof ManualControl> = {
    w: "x",
    s: "x",
    a: "y",
    d: "y",
    q: "z",
    e: "z",
    ArrowLeft: "r",
    ArrowRight: "r",
  };

  const KEY_DIRECTION: Record<string, number> = {
    w: 1,
    s: -1,
    a: -1,
    d: 1,
    q: 1,
    e: -1,
    ArrowLeft: -1,
    ArrowRight: 1,
  };

  /**
   * 计算控制输入值
   */
  const calculateControl = useCallback((): ManualControl => {
    const control: ManualControl = { x: 0, y: 0, z: 0, r: 0 };
    const step = 100; // 每次按键增减的步长

    for (const key of keysPressedRef.current) {
      const axis = KEY_MAP[key];
      const direction = KEY_DIRECTION[key];

      if (axis && direction) {
        control[axis] = Math.max(
          -1000,
          Math.min(1000, control[axis] + direction * step)
        );
      }
    }

    return control;
  }, []);

  /**
   * 控制循环（10Hz）
   */
  const startControlLoop = useCallback(() => {
    if (controlLoopRef.current) {
      return;
    }

    let lastSendTime = 0;
    const SEND_INTERVAL = 100; // 100ms = 10Hz

    const loop = (timestamp: number) => {
      if (timestamp - lastSendTime >= SEND_INTERVAL) {
        let control: ManualControl;

        // 优先使用游戏手柄输入
        if (gamepad.connected && gamepad.axes.length >= 4) {
          control = mapGamepadToControl(gamepad.axes, gamepad.buttons);
        } else {
          // 退回到键盘输入
          control = calculateControl();
        }

        setControlInput(control);

        // 如果已启用控制，发送指令
        if (isArmed && (control.x !== 0 || control.y !== 0 || control.z !== 0 || control.r !== 0)) {
          sendControl(control);
        }

        lastSendTime = timestamp;
      }

      controlLoopRef.current = requestAnimationFrame(loop);
    };

    controlLoopRef.current = requestAnimationFrame(loop);
  }, [calculateControl, isArmed, sendControl, gamepad]);

  /**
   * 停止控制循环
   */
  const stopControlLoop = useCallback(() => {
    if (controlLoopRef.current) {
      cancelAnimationFrame(controlLoopRef.current);
      controlLoopRef.current = null;
    }
  }, []);

  /**
   * 键盘按下事件
   */
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    const key = event.key.toLowerCase();

    // 只处理映射的按键
    if (KEY_MAP[key] || KEY_MAP[event.key]) {
      keysPressedRef.current.add(key);
      event.preventDefault();
    }
  }, []);

  /**
   * 键盘抬起事件
   */
  const handleKeyUp = useCallback((event: KeyboardEvent) => {
    const key = event.key.toLowerCase();
    keysPressedRef.current.delete(key);
  }, []);

  /**
   * 切换控制启用状态
   */
  const toggleArm = useCallback(() => {
    setIsArmed((prev) => !prev);
  }, []);

  /**
   * 获取连接状态文本
   */
  const getStatusText = () => {
    switch (status) {
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
  const getStatusClass = () => {
    switch (status) {
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

  /**
   * 挂载键盘事件监听
   */
  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      stopControlLoop();
    };
  }, [handleKeyDown, handleKeyUp, stopControlLoop]);

  /**
   * 控制启用时启动控制循环
   */
  useEffect(() => {
    if (isArmed) {
      startControlLoop();
    } else {
      stopControlLoop();
    }

    return () => {
      stopControlLoop();
    };
  }, [isArmed, startControlLoop, stopControlLoop]);

  return (
    <div className="panel control-panel" style={{
      background: 'rgba(26, 29, 35, 0.95)',
      border: '1px solid rgba(255, 255, 255, 0.1)',
      borderRadius: '8px',
      padding: '16px',
      marginBottom: '8px',
    }}>
      <h3 style={{
        fontSize: '12px',
        fontWeight: 'bold',
        color: '#94a3b8',
        textTransform: 'uppercase',
        letterSpacing: '1.5px',
        marginBottom: '12px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
      }}>
        <span style={{ fontSize: '16px' }}>🎮</span>
        控制面板
      </h3>

      {/* 连接状态 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '8px',
        padding: '8px',
        background: 'rgba(255, 255, 255, 0.03)',
        borderRadius: '4px',
      }}>
        <span style={{ fontSize: '10px', color: '#64748b' }}>WebSocket:</span>
        <span style={{
          fontSize: '10px',
          fontWeight: 'bold',
          color: status === 'connected' ? '#10b981' : status === 'connecting' ? '#f59e0b' : '#ef4444',
        }}>
          {getStatusText()}
        </span>
      </div>

      {/* 游戏手柄状态 */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '12px',
        padding: '8px',
        background: 'rgba(255, 255, 255, 0.03)',
        borderRadius: '4px',
      }}>
        <span style={{ fontSize: '10px', color: '#64748b' }}>游戏手柄:</span>
        <span style={{
          fontSize: '10px',
          fontWeight: 'bold',
          color: gamepad.connected ? '#10b981' : '#64748b',
        }}>
          {gamepad.connected ? '已连接 ✓' : '未连接'}
        </span>
      </div>

      {/* 游戏手柄提示 */}
      {!gamepad.connected && (
        <div style={{
          marginBottom: '12px',
          padding: '8px',
          background: 'rgba(59, 130, 246, 0.1)',
          border: '1px solid rgba(59, 130, 246, 0.3)',
          borderRadius: '4px',
          fontSize: '9px',
          color: '#93c5fd',
        }}>
          💡 提示: 连接游戏手柄后，请按下手柄上的任意按钮激活
        </div>
      )}

      {/* 控制启用按钮 */}
      <button
        onClick={toggleArm}
        disabled={status !== "connected"}
        style={{
          width: '100%',
          padding: '10px',
          marginBottom: '12px',
          border: 'none',
          borderRadius: '6px',
          fontSize: '11px',
          fontWeight: 'bold',
          textTransform: 'uppercase',
          letterSpacing: '1px',
          cursor: status === "connected" ? 'pointer' : 'not-allowed',
          transition: 'all 0.2s',
          background: isArmed
            ? 'linear-gradient(135deg, #10b981 0%, #059669 100%)'
            : 'linear-gradient(135deg, #3b82f6 0%, #2563eb 100%)',
          color: 'white',
          boxShadow: isArmed
            ? '0 2px 8px rgba(16, 185, 129, 0.4)'
            : '0 2px 8px rgba(59, 130, 246, 0.4)',
          opacity: status === "connected" ? 1 : 0.5,
        }}
      >
        {isArmed ? "✓ 控制已启用" : "启用控制"}
      </button>

      {/* 速率限制警告 */}
      {isRateLimited && (
        <div style={{
          marginBottom: '12px',
          padding: '8px',
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: '4px',
          fontSize: '9px',
          color: '#fca5a5',
        }}>
          ⚠️ 控制速率受限 (20Hz)
        </div>
      )}

      {/* 控制输入显示 */}
      <div style={{ marginBottom: '12px' }}>
        <div style={{ fontSize: '9px', color: '#64748b', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '1px' }}>
          实时输入
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
          <div style={{
            padding: '6px',
            background: 'rgba(255, 255, 255, 0.03)',
            borderRadius: '4px',
          }}>
            <div style={{ fontSize: '8px', color: '#64748b' }}>前进/后退</div>
            <div style={{ fontSize: '12px', fontFamily: 'monospace', color: '#e2e8f0' }}>
              {controlInput.x > 0 ? '+' : ''}{controlInput.x}
            </div>
          </div>
          <div style={{
            padding: '6px',
            background: 'rgba(255, 255, 255, 0.03)',
            borderRadius: '4px',
          }}>
            <div style={{ fontSize: '8px', color: '#64748b' }}>左右平移</div>
            <div style={{ fontSize: '12px', fontFamily: 'monospace', color: '#e2e8f0' }}>
              {controlInput.y > 0 ? '+' : ''}{controlInput.y}
            </div>
          </div>
          <div style={{
            padding: '6px',
            background: 'rgba(255, 255, 255, 0.03)',
            borderRadius: '4px',
          }}>
            <div style={{ fontSize: '8px', color: '#64748b' }}>上下控制</div>
            <div style={{ fontSize: '12px', fontFamily: 'monospace', color: '#e2e8f0' }}>
              {controlInput.z > 0 ? '+' : ''}{controlInput.z}
            </div>
          </div>
          <div style={{
            padding: '6px',
            background: 'rgba(255, 255, 255, 0.03)',
            borderRadius: '4px',
          }}>
            <div style={{ fontSize: '8px', color: '#64748b' }}>转向</div>
            <div style={{ fontSize: '12px', fontFamily: 'monospace', color: '#e2e8f0' }}>
              {controlInput.r > 0 ? '+' : ''}{controlInput.r}
            </div>
          </div>
        </div>
      </div>

      {/* 最后一次 ACK 显示 */}
      {lastAck && (
        <div style={{
          marginBottom: '12px',
          padding: '8px',
          background: lastAck.result === "ACCEPTED"
            ? 'rgba(16, 185, 129, 0.1)'
            : 'rgba(239, 68, 68, 0.1)',
          border: `1px solid ${lastAck.result === "ACCEPTED"
            ? 'rgba(16, 185, 129, 0.3)'
            : 'rgba(239, 68, 68, 0.3)'}`,
          borderRadius: '4px',
        }}>
          <div style={{ fontSize: '9px', color: '#64748b' }}>最后一次指令</div>
          <div style={{
            fontSize: '10px',
            fontWeight: 'bold',
            color: lastAck.result === "ACCEPTED" ? '#10b981' : '#ef4444',
          }}>
            {lastAck.result} · {lastAck.latency_ms.toFixed(1)}ms
          </div>
        </div>
      )}

      {/* 操作说明 */}
      <div style={{
        padding: '8px',
        background: 'rgba(255, 255, 255, 0.02)',
        borderRadius: '4px',
        borderTop: '1px solid rgba(255, 255, 255, 0.05)',
      }}>
        <div style={{ fontSize: '8px', color: '#64748b', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
          操作说明
        </div>
        <div style={{ fontSize: '8px', color: '#94a3b8', lineHeight: '1.6' }}>
          🎮 左摇杆: 前进/后退 + 平移<br/>
          🎮 右摇杆: 上下控制<br/>
          🎮 LB/RB: 左右转向<br/>
          ⌨️ 键盘: W/S/A/D, Q/E, ←/→
        </div>
      </div>
    </div>
  );
}
