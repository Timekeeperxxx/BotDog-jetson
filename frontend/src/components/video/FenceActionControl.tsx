import { useFenceDetection } from '../../hooks/useFenceDetection';
import { useAuthState } from '../../stores/authStore';

export function FenceActionControl() {
  const { status, loading, error, setEnabled } = useFenceDetection();
  const { role } = useAuthState();
  const canOperate = role === 'operator' || role === 'admin';
  const enabled = status?.enabled === true;
  const stateLabel = loading
    ? '正在切换…'
    : status === null
      ? error ? '状态读取失败' : '正在读取板端状态…'
      : enabled ? '已开启 · 动作告警与抓拍' : '已关闭';

  return (
    <div className="mb-3 border-b border-white/10 pb-3">
      <button
        type="button"
        role="switch"
        aria-label="围栏动作识别"
        aria-checked={enabled}
        aria-busy={loading}
        disabled={!canOperate || status === null || loading}
        onClick={() => void setEnabled(!enabled)}
        className="flex w-full items-center gap-3 rounded-lg border border-amber-300/25 bg-amber-300/[0.06] px-3 py-2 text-left disabled:opacity-50"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] font-black text-white">围栏动作识别</span>
          <span className="block text-[9px] text-white/55">{stateLabel}</span>
          <span className="block text-[9px] text-white/45">攀爬、翻越、破坏动作、蹲伏、徘徊</span>
        </span>
        <span className={`relative h-5 w-9 shrink-0 rounded-full ${enabled ? 'bg-amber-300' : 'bg-white/15'}`}>
          <span className={`absolute left-0 top-0.5 h-4 w-4 rounded-full bg-black transition-transform ${enabled ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
        </span>
      </button>
      {!canOperate && <p className="mt-2 text-[10px] text-white/45">操作员或管理员可切换</p>}
      {error && <p role="alert" className="mt-2 text-[10px] text-red-300">{error}</p>}
    </div>
  );
}
