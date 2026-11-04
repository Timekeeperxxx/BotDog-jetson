import { CircleStop } from 'lucide-react';
import type { UseRobotControlReturn } from '../../hooks/useRobotControl';
import { hasAuthSession, hasRole, useAuthState } from '../../stores/authStore';

export function ConsoleStopBar({ control }: { control: UseRobotControlReturn }) {
  useAuthState();
  const canOperate = hasAuthSession() && hasRole('operator');
  const { stopStatus, stopCommand, resultMessage } = control;
  const message = stopStatus === 'idle'
    ? '手动控制 · 松手停止运动'
    : stopStatus === 'confirmed'
      ? '手动停车已确认'
      : resultMessage;

  return (
    <section className="console-stop-bar" aria-label="手动停车" data-state={stopStatus}>
      <button
        type="button"
        onClick={stopCommand}
        disabled={!canOperate || stopStatus === 'waiting'}
      >
        <CircleStop size={22} aria-hidden="true" />
        {stopStatus === 'waiting' ? '等待停车确认…' : '立即停车'}
      </button>
      <div role="status" aria-live="polite">
        {canOperate ? message : '操作员登录后可手动停车'}
      </div>
    </section>
  );
}
