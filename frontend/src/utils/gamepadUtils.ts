/**
 * 游戏手柄工具函数
 *
 * 包含死区处理、控制映射等工具函数
 */

import type { ManualControl } from '../types/telemetry';

/**
 * 应用径向死区过滤
 *
 * 径向死区比轴向死区更适合模拟摇杆，因为它考虑了两个轴的组合运动。
 * 这可以防止摇杆漂移和微小的硬件误差。
 *
 * @param x X 轴值 (-1.0 ~ 1.0)
 * @param y Y 轴值 (-1.0 ~ 1.0)
 * @param threshold 死区阈值 (推荐 0.15)
 * @returns 过滤后的 [x, y] 值
 *
 * @example
 * // 在死区内（返回 0）
 * applyDeadzone(0.05, 0.05, 0.15); // [0, 0]
 *
 * // 在死区外（归一化）
 * applyDeadzone(0.5, 0.5, 0.15); // [0.41, 0.41]
 */
export function applyDeadzone(
  x: number,
  y: number,
  threshold: number = 0.15
): [number, number] {
  // 计算摇杆位置的径向距离
  const magnitude = Math.sqrt(x * x + y * y);

  // 如果在死区内，返回 0
  if (magnitude < threshold) {
    return [0, 0];
  }

  // 归一化并保留完整的输出范围
  // 这确保即使有死区，摇杆仍能达到 -1.0 到 1.0 的完整范围
  const normalizedMagnitude = (magnitude - threshold) / (1 - threshold);
  const scale = normalizedMagnitude / magnitude;

  return [x * scale, y * scale];
}

/**
 * 应用轴向死区过滤（简单版本）
 *
 * 对每个轴独立应用死区，适用于方向键或单个轴的控制。
 * 对于模拟摇杆，推荐使用径向死区（applyDeadzone）。
 *
 * @param value 轴值 (-1.0 ~ 1.0)
 * @param threshold 死区阈值 (推荐 0.15)
 * @returns 过滤后的值
 */
export function applyAxialDeadzone(
  value: number,
  threshold: number = 0.15
): number {
  if (Math.abs(value) < threshold) {
    return 0;
  }

  // 归一化并保留完整范围
  const sign = value > 0 ? 1 : -1;
  const normalized = (Math.abs(value) - threshold) / (1 - threshold);

  return sign * normalized;
}

/**
 * 将游戏手柄输入映射到机器狗控制指令
 *
 * 映射规则:
 * - 左摇杆 Y 轴: 前进/后退 (x)
 * - 左摇杆 X 轴: 左右平移 (y)
 * - 右摇杆 Y 轴: 上下控制 (z)
 * - 肩部按钮 LB/RB: 左右转向 (r)
 *
 * @param axes 摇杆数组 [leftX, leftY, rightX, rightY]
 * @param buttons 按钮数组 (至少需要 6 个按钮)
 * @returns ManualControl 对象，值范围 -1000 到 1000
 */
export function mapGamepadToControl(
  axes: number[],
  buttons: boolean[]
): ManualControl {
  // 确保至少有 4 个轴和 6 个按钮
  if (axes.length < 4) {
    console.warn('游戏手柄轴数量不足:', axes.length);
    return { x: 0, y: 0, z: 0, r: 0 };
  }

  if (buttons.length < 6) {
    console.warn('游戏手柄按钮数量不足:', buttons.length);
  }

  // 应用径向死区过滤摇杆输入
  const [leftX, leftY] = applyDeadzone(axes[0], axes[1], 0.15);
  const [, rightY] = applyDeadzone(axes[2], axes[3], 0.15);

  // 映射到控制指令并转换为 -1000 到 1000 范围
  const x = Math.round(-leftY * 1000);   // 左摇杆 Y: 前进/后退（Y 轴向上为负，需反转）
  const y = Math.round(leftX * 1000);    // 左摇杆 X: 左右平移
  const z = Math.round(-rightY * 1000);  // 右摇杆 Y: 上下（Y 轴向上为负，需反转）

  // 肩部按钮控制偏航转向
  let r = 0;
  if (buttons[4]) r -= 500;  // LB: 左转
  if (buttons[5]) r += 500;  // RB: 右转

  return { x, y, z, r };
}

/**
 * 格式化游戏手柄 ID 为简短名称
 *
 * @param id 游戏手柄完整 ID 字符串
 * @returns 简短的控制器名称
 *
 * @example
 * formatGamepadId('Xbox 360 Controller (XInput STANDARD GAMEPAD)');
 * // 返回: 'Xbox 360 Controller'
 */
export function formatGamepadId(id: string): string {
  // 移除括号内容和多余空格
  const cleaned = id.replace(/\([^)]*\)/g, '').trim();

  // 限制长度
  if (cleaned.length > 30) {
    return cleaned.substring(0, 27) + '...';
  }

  return cleaned;
}

/**
 * 检测游戏手柄是否为标准映射
 *
 * @param gamepad Gamepad 对象
 * @returns 是否使用标准映射
 */
export function isStandardGamepad(gamepad: Gamepad | null): boolean {
  if (!gamepad) return false;
  return gamepad.mapping === 'standard';
}

/**
 * 获取游戏手柄状态摘要（用于调试）
 *
 * @param gamepad Gamepad 对象
 * @returns 状态摘要字符串
 */
export function getGamepadSummary(gamepad: Gamepad | null): string {
  if (!gamepad) return '无游戏手柄';

  const pressedButtons = gamepad.buttons
    .map((btn, idx) => (btn.pressed ? idx : -1))
    .filter((idx) => idx >= 0);

  const axesSummary = gamepad.axes
    .map((axis, idx) => `${idx}:${axis.toFixed(2)}`)
    .join(', ');

  return `游戏手柄: ${gamepad.id}\n按下的按钮: ${pressedButtons.join(', ')}\n轴: ${axesSummary}`;
}
