/**
 * 机器狗控制面板组件（3×3 九宫格版）
 *
 * 布局：
 * 行1: [左旋转] [前进]  [右旋转]
 * 行2: [左平移] [后退]  [右平移]
 * 行3: [起立]   [    ]  [下蹲]
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowUp,
  ArrowDown,
  RotateCcw,
  RotateCw,
  ChevronsDown,
  ChevronsUp,
  ArrowLeftFromLine,
  ArrowRightFromLine,
  AlertCircle,
} from 'lucide-react';
import { useRobotControl, type RobotCommand, type RobotCommandOptions } from '../hooks/useRobotControl';
import { hasAuthSession, hasRole, useAuthState } from '../stores/authStore';
import {
  DEFAULT_LINEAR_SPEED,
  DEFAULT_TURN_SPEED,
  MAX_LINEAR_SPEED,
  MAX_TURN_SPEED,
  SPEED_STEP,
  clampSpeed,
  formatSpeed,
  isArrowSpeedKey,
} from '../utils/speedControl';

interface ControlPadProps {
  isDisabled?: boolean;
  bottomCenterSlot?: React.ReactNode;
}

interface ButtonConfig {
  cmd: RobotCommand | null;  // null = 占位空格
  label: string;
  icon: React.ReactNode;
}

// 3×3 九宫格布局
const BUTTONS: ButtonConfig[] = [
  // 第一行：旋转 + 前进
  { cmd: 'left',         label: '左旋转', icon: <RotateCcw size={14} /> },
  { cmd: 'forward',      label: '前进',   icon: <ArrowUp size={14} /> },
  { cmd: 'right',        label: '右旋转', icon: <RotateCw size={14} /> },
  // 第二行：平移 + 后退
  { cmd: 'strafe_left',  label: '左平移', icon: <ArrowLeftFromLine size={14} /> },
  { cmd: 'backward',     label: '后退',   icon: <ArrowDown size={14} /> },
  { cmd: 'strafe_right', label: '右平移', icon: <ArrowRightFromLine size={14} /> },
  // 第三行：姿态
  { cmd: 'stand',        label: '起立',   icon: <ChevronsUp size={14} /> },
  { cmd: null,           label: '',       icon: null },
  { cmd: 'sit',          label: '下蹲',   icon: <ChevronsDown size={14} /> },
];

export function ControlPad({ isDisabled = false, bottomCenterSlot }: ControlPadProps) {
  useAuthState();
  const canOperate = hasAuthSession() && hasRole('operator');
  const { startCommand, stopCommand, isControlling, lastResult, currentCmd, resultMessage } =
    useRobotControl();
  const [linearSpeed, setLinearSpeed] = useState(DEFAULT_LINEAR_SPEED);
  const [turnSpeed, setTurnSpeed] = useState(DEFAULT_TURN_SPEED);
  const linearSpeedRef = useRef(DEFAULT_LINEAR_SPEED);
  const turnSpeedRef = useRef(DEFAULT_TURN_SPEED);

  const getCommandOptions = useCallback((cmd: RobotCommand): RobotCommandOptions => {
    if (cmd === 'forward' || cmd === 'backward') {
      return { vx: linearSpeedRef.current };
    }
    if (cmd === 'left' || cmd === 'right') {
      return { vyaw: turnSpeedRef.current };
    }
    return {};
  }, []);

  const startControlCommand = useCallback((cmd: RobotCommand) => {
    startCommand(cmd, getCommandOptions(cmd));
  }, [getCommandOptions, startCommand]);

  const adjustKeyboardSpeed = useCallback((key: string) => {
    let nextLinearSpeed = linearSpeedRef.current;
    let nextTurnSpeed = turnSpeedRef.current;

    if (key === 'ArrowUp') {
      nextLinearSpeed = clampSpeed(nextLinearSpeed + SPEED_STEP, MAX_LINEAR_SPEED);
    } else if (key === 'ArrowDown') {
      nextLinearSpeed = clampSpeed(nextLinearSpeed - SPEED_STEP, MAX_LINEAR_SPEED);
    } else if (key === 'ArrowLeft') {
      nextTurnSpeed = clampSpeed(nextTurnSpeed + SPEED_STEP, MAX_TURN_SPEED);
    } else if (key === 'ArrowRight') {
      nextTurnSpeed = clampSpeed(nextTurnSpeed - SPEED_STEP, MAX_TURN_SPEED);
    }

    linearSpeedRef.current = nextLinearSpeed;
    turnSpeedRef.current = nextTurnSpeed;
    setLinearSpeed(nextLinearSpeed);
    setTurnSpeed(nextTurnSpeed);
  }, []);

  const handlePointerDown = (cmd: RobotCommand) => (e: React.PointerEvent) => {
    if (isDisabled || !canOperate) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    startControlCommand(cmd);
  };

  const handlePointerUp = () => {
    if (isDisabled || !canOperate) return;
    stopCommand();
  };

  // 键盘控制逻辑
  useEffect(() => {
    if (isDisabled || !canOperate) {
      if (isControlling) stopCommand();
      return;
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return;
      if (e.repeat) return; // 防止长按重复触发

      if (isArrowSpeedKey(e.key)) {
        e.preventDefault();
        adjustKeyboardSpeed(e.key);
        return;
      }

      let cmd: RobotCommand | null = null;
      switch (e.key.toLowerCase()) {
        case 'w': cmd = 'forward'; break;
        case 's': cmd = 'backward'; break;
        case 'a': cmd = 'strafe_left'; break;
        case 'd': cmd = 'strafe_right'; break;
        case 'q': cmd = 'left'; break;
        case 'e': cmd = 'right'; break;
        case 'control': cmd = 'sit'; break;
        case 'shift': cmd = 'stand'; break;
      }

      if (cmd) {
        e.preventDefault();
        startControlCommand(cmd);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return;
      if (isArrowSpeedKey(e.key)) {
        e.preventDefault();
        return;
      }

      let cmd: RobotCommand | null = null;
      switch (e.key.toLowerCase()) {
        case 'w': cmd = 'forward'; break;
        case 's': cmd = 'backward'; break;
        case 'a': cmd = 'strafe_left'; break;
        case 'd': cmd = 'strafe_right'; break;
        case 'q': cmd = 'left'; break;
        case 'e': cmd = 'right'; break;
        case 'control': cmd = 'sit'; break;
        case 'shift': cmd = 'stand'; break;
      }

      if (cmd && currentCmd === cmd) {
        e.preventDefault();
        stopCommand();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [adjustKeyboardSpeed, isDisabled, canOperate, isControlling, currentCmd, startControlCommand, stopCommand]);

  const resultColor =
    lastResult?.result === 'ACCEPTED'
      ? 'text-emerald-400'
      : lastResult?.result === 'REJECTED_E_STOP' || lastResult?.result === 'REJECTED_ADAPTER_ERROR'
      ? 'text-red-400'
      : 'text-yellow-400';

  return (
    <div className={`select-none ${isDisabled || !canOperate ? 'opacity-40 pointer-events-none' : ''}`}>
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[9px] font-black uppercase tracking-widest text-white/70">
          移动控制
        </span>
        {isControlling && (
          <span className="flex items-center gap-1">
            <span className="w-1 h-1 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-[8px] font-black text-emerald-400">{currentCmd}</span>
          </span>
        )}
      </div>

      {/* 3×3 九宫格 */}
      <div className="grid grid-cols-3 gap-1">
        {BUTTONS.map(({ cmd, label, icon }, idx) => {
          // 空位占位
          if (cmd === null) {
            return (
              <div key={`empty-${idx}`} className="h-8">
                {bottomCenterSlot}
              </div>
            );
          }

          return (
            <button
              key={cmd}
              onPointerDown={handlePointerDown(cmd)}
              onPointerUp={handlePointerUp}
              onPointerLeave={handlePointerUp}
              onContextMenu={(e) => e.preventDefault()}
              className={`
                flex flex-col items-center justify-center gap-0.5
                h-8 rounded border
                font-black text-[7px] uppercase tracking-tight
                transition-all duration-100 cursor-pointer select-none touch-none
                ${
                  currentCmd === cmd && isControlling
                    ? 'bg-white text-black border-white shadow-[0_0_8px_white]'
                    : 'bg-zinc-800/80 text-white/60 border-white/15 hover:border-white/50 hover:text-white'
                }
              `}
            >
              {icon}
              <span>{label}</span>
            </button>
          );
        })}
      </div>

      {/* 状态栏 */}
      <div className="mt-1.5 min-h-[12px] flex flex-col gap-0.5 font-mono">
        {resultMessage && (
          <div className={`flex items-center gap-1 text-[8px] font-black italic ${resultColor}`}>
            <AlertCircle size={8} />
            <span>{resultMessage}</span>
          </div>
        )}
        <div className="flex items-center justify-between text-[8px]">
          {lastResult ? (
            <>
              <span className="text-white/60">{lastResult.ack_cmd}</span>
              <span className={`${resultColor} font-black opacity-80`}>{lastResult.result}</span>
              <span className="text-white/60">{lastResult.latency_ms}ms</span>
            </>
          ) : (
            <span className="text-white/60 w-full text-center tracking-tighter">
              {canOperate ? 'W/S/Q/E 控制，方向键调速' : '登录后可进行手动控制'}
            </span>
          )}
        </div>
        {canOperate && (
          <div className="flex items-center justify-between text-[8px] text-white/60">
            <span>前后 {formatSpeed(linearSpeed)} m/s</span>
            <span>转向 {formatSpeed(turnSpeed)} rad/s</span>
          </div>
        )}
      </div>
    </div>
  );
}
