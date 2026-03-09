/**
 * 游戏手柄输入 Hook
 *
 * 使用浏览器 Gamepad API 来轮询游戏手柄状态。
 * 支持自动检测连接/断开事件。
 *
 * 参考: https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import type { GamepadState } from '../types/gamepad';

/**
 * 游戏手柄输入 Hook
 *
 * @param gamepadIndex 游戏手柄索引 (0-3，默认 0)
 * @returns 游戏手柄状态
 *
 * @example
 * const gamepad = useGamepad(0);
 *
 * if (gamepad.connected) {
 *   console.log('控制器:', gamepad.id);
 *   console.log('摇杆:', gamepad.axes);
 *   console.log('按钮:', gamepad.buttons);
 * }
 */
export function useGamepad(gamepadIndex: number = 0): GamepadState {
  const [state, setState] = useState<GamepadState>({
    connected: false,
    id: null,
    buttons: [],
    axes: [],
  });

  const requestRef = useRef<number>();
  const gamepadRef = useRef<Gamepad | null>(null);

  /**
   * 轮询游戏手柄状态
   *
   * Gamepad API 不会自动推送更新，需要持续轮询。
   * 使用 requestAnimationFrame 以 60Hz 速率轮询，与浏览器刷新率同步。
   */
  const pollGamepad = useCallback(() => {
    // 获取所有连接的游戏手柄
    const gamepads = navigator.getGamepads();

    // 调试：输出所有检测到的游戏手柄
    if (gamepads.length > 0) {
      const connectedCount = Array.from(gamepads).filter(g => g !== null).length;
      if (connectedCount > 0 && !state.connected) {
        console.log('🔍 检测到游戏手柄，但未激活。请按下手柄按钮激活。');
        gamepads.forEach((g, idx) => {
          if (g) {
            console.log(`   手柄 ${idx}: ${g.id}, mapping: ${g.mapping}`);
          }
        });
      }
    }

    const gamepad = gamepads[gamepadIndex];

    if (gamepad && gamepad.mapping === 'standard') {
      // 更新游戏手柄引用
      gamepadRef.current = gamepad;

      // 提取按钮状态（pressed 属性）
      const buttonStates = gamepad.buttons.map((btn) => btn.pressed);

      // 转换轴数据为普通数组
      const axes = Array.from(gamepad.axes);

      // 更新状态
      setState({
        connected: true,
        id: gamepad.id,
        buttons: buttonStates,
        axes: axes,
      });
    } else {
      // 游戏手柄未连接或非标准映射
      gamepadRef.current = null;
      setState({
        connected: false,
        id: null,
        buttons: [],
        axes: [],
      });
    }

    // 继续下一帧轮询
    requestRef.current = requestAnimationFrame(pollGamepad);
  }, [gamepadIndex, state.connected]);

  /**
   * 启动轮询循环
   *
   * 组件挂载时启动，卸载时清理。
   */
  useEffect(() => {
    // 开始轮询
    pollGamepad();

    // 清理函数：取消动画帧请求
    return () => {
      if (requestRef.current) {
        cancelAnimationFrame(requestRef.current);
      }
    };
  }, [pollGamepad]);

  /**
   * 监听游戏手柄连接/断开事件
   *
   * 这些事件在全局 window 对象上触发。
   */
  useEffect(() => {
    const handleConnect = (event: GamepadEvent) => {
      if (event.gamepad.index === gamepadIndex) {
        console.log(`🎮 游戏手柄已连接: ${event.gamepad.id}`);
        console.log(`   映射类型: ${event.gamepad.mapping || 'non-standard'}`);
        console.log(`   按钮数量: ${event.gamepad.buttons.length}`);
        console.log(`   轴数量: ${event.gamepad.axes.length}`);
      }
    };

    const handleDisconnect = (event: GamepadEvent) => {
      if (event.gamepad.index === gamepadIndex) {
        console.log(`🔌 游戏手柄已断开: ${event.gamepad.id}`);
        gamepadRef.current = null;
      }
    };

    // 添加事件监听器
    window.addEventListener('gamepadconnected', handleConnect);
    window.addEventListener('gamepaddisconnected', handleDisconnect);

    // 清理函数：移除事件监听器
    return () => {
      window.removeEventListener('gamepadconnected', handleConnect);
      window.removeEventListener('gamepaddisconnected', handleDisconnect);
    };
  }, [gamepadIndex]);

  return state;
}

/**
 * 获取所有已连接的游戏手柄数量
 *
 * @returns 已连接的游戏手柄数量 (0-4)
 */
export function getConnectedGamepadCount(): number {
  const gamepads = navigator.getGamepads();
  let count = 0;

  for (const gamepad of gamepads) {
    if (gamepad && gamepad.connected) {
      count++;
    }
  }

  return count;
}

/**
 * 检查浏览器是否支持 Gamepad API
 *
 * @returns 是否支持 Gamepad API
 */
export function isGamepadSupported(): boolean {
  return 'getGamepads' in navigator;
}
