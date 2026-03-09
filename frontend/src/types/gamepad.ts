/**
 * 游戏手柄相关的类型定义
 *
 * 参考: https://www.w3.org/TR/gamepad/
 */

/**
 * 游戏手柄按钮映射（标准布局）
 *
 * 支持 Xbox 和 PlayStation 控制器的标准映射
 */
export const GAMEPAD_BUTTONS = {
  // 面部按钮
  A: 0,   // Xbox A / PlayStation Cross (✕)
  B: 1,   // Xbox B / PlayStation Circle (○)
  X: 2,   // Xbox X / PlayStation Square (□)
  Y: 3,   // Xbox Y / PlayStation Triangle (△)

  // 肩部按钮
  LB: 4,  // Left Bumper / L1
  RB: 5,  // Right Bumper / R1
  LT: 6,  // Left Trigger / L2 (analog)
  RT: 7,  // Right Trigger / R2 (analog)

  // 中央按钮
  BACK: 8,   // View/Back / Share/Create
  START: 9,  // Menu/Start / Options

  // 摇杆按下
  L3: 10,  // Left Stick Click / L3
  R3: 11,  // Right Stick Click / R3
} as const;

/**
 * 游戏手柄按钮名称类型
 */
export type GamepadButtonName = keyof typeof GAMEPAD_BUTTONS;

/**
 * 游戏手柄轴映射
 */
export const GAMEPAD_AXES = {
  LEFT_STICK_X: 0,   // 左摇杆水平 (-1.0 ~ 1.0)
  LEFT_STICK_Y: 1,   // 左摇杆垂直 (-1.0 ~ 1.0)
  RIGHT_STICK_X: 2,  // 右摇杆水平 (-1.0 ~ 1.0)
  RIGHT_STICK_Y: 3,  // 右摇杆垂直 (-1.0 ~ 1.0)
} as const;

/**
 * 游戏手柄轴名称类型
 */
export type GamepadAxisName = keyof typeof GAMEPAD_AXES;

/**
 * 游戏手柄状态
 */
export interface GamepadState {
  connected: boolean;      // 是否已连接
  id: string | null;       // 控制器 ID (例如: "Xbox Controller")
  buttons: boolean[];      // 按钮按下状态数组
  axes: number[];          // 摇杆位置数组 (-1.0 ~ 1.0)
}

/**
 * 死区配置
 */
export interface DeadzoneConfig {
  threshold: number;  // 死区阈值 (0.0 ~ 1.0)，推荐 0.15
  radial: boolean;    // 使用径向死区（推荐）或轴向死区
}
