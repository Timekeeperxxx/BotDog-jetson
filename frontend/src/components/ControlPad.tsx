/**
 * 机器狗控制面板组件（3×3 九宫格版）
 *
 * 布局：
 * 行1: [左旋转] [前进]  [右旋转]
 * 行2: [左平移] [后退]  [右平移]
 * 行3: [起立]   [    ]  [下蹲]
 */

import React, { useCallback } from 'react';
import {
  ArrowUp,
  ArrowDown,
  RotateCcw,
  RotateCw,
  ChevronsDown,
  ChevronsUp,
  ArrowLeftFromLine,
  ArrowRightFromLine,
} from 'lucide-react';
import { useRobotControl, type RobotCommand } from '../hooks/useRobotControl';

interface ControlPadProps {
  isDisabled?: boolean;
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

export function ControlPad({ isDisabled = false }: ControlPadProps) {
  const { startCommand, stopCommand, isControlling, lastResult, currentCmd } =
    useRobotControl();

  const handlePointerDown = useCallback(
    (cmd: RobotCommand) => (e: React.PointerEvent) => {
      if (isDisabled) return;
      e.currentTarget.setPointerCapture(e.pointerId);
      startCommand(cmd);
    },
    [isDisabled, startCommand]
  );

  const handlePointerUp = useCallback(() => {
    if (isDisabled) return;
    stopCommand();
  }, [isDisabled, stopCommand]);

  const resultColor =
    lastResult?.result === 'ACCEPTED'
      ? 'text-emerald-400'
      : lastResult?.result === 'REJECTED_E_STOP'
      ? 'text-red-400'
      : 'text-yellow-400';

  return (
    <div className={`select-none ${isDisabled ? 'opacity-40 pointer-events-none' : ''}`}>
      {/* 标题栏 */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[9px] font-black uppercase tracking-widest text-white/40">
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
            return <div key={`empty-${idx}`} className="h-8" />;
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
      <div className="mt-1.5 flex items-center justify-between text-[8px] font-mono">
        {lastResult ? (
          <>
            <span className="text-white/30">{lastResult.ack_cmd}</span>
            <span className={resultColor}>{lastResult.result}</span>
            <span className="text-white/30">{lastResult.latency_ms}ms</span>
          </>
        ) : (
          <span className="text-white/20 w-full text-center">按住按钮控制机器狗</span>
        )}
      </div>
    </div>
  );
}
