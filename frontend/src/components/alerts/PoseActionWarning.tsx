import { useEffect, useState } from 'react';

function ActionLabel({ active, label }: { active: boolean; label: string }) {
  const [visible, setVisible] = useState(active);
  useEffect(() => {
    if (active) {
      setVisible(true);
      return;
    }
    const timer = window.setTimeout(() => setVisible(false), 1000);
    return () => window.clearTimeout(timer);
  }, [active]);
  if (!active && !visible) return null;
  return <span className="rounded-lg border border-amber-300 bg-amber-950/95 px-4 py-2 font-bold text-amber-100 shadow-lg">
    {label}{!active && <small className="ml-2 font-normal">结束后保留</small>}
  </span>;
}

export function PoseActionWarning({ actions }: { actions?: string[] }) {
  return <div role="status" aria-label="持续动作警告" className="pointer-events-none absolute left-1/2 top-16 z-30 flex -translate-x-1/2 flex-wrap justify-center gap-2 whitespace-nowrap text-sm">
    <ActionLabel active={actions?.includes('POSE_DAMAGE_SUSPECTED') ?? false} label="疑似破坏动作" />
    <ActionLabel active={actions?.includes('POSE_CLIMBING_SUSPECTED') ?? false} label="疑似攀爬 / 翻越" />
  </div>;
}
