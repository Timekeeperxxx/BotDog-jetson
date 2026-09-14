import { alertSummary } from '../../hooks/alertEventPolicy';
import { getApiUrl } from '../../config/api';
import type { AlertEvent } from '../../types/event';

function getImageUrl(imageUrl?: string | null): string | null {
  if (!imageUrl) return null;
  if (imageUrl.startsWith('http://') || imageUrl.startsWith('https://')) {
    return imageUrl;
  }
  return getApiUrl(imageUrl);
}

export interface DetectionAlertProps {
  data: AlertEvent;
  onOpenEvidence: (id: number) => void;
}

export function DetectionAlert({ data, onOpenEvidence }: DetectionAlertProps) {
  const severity = String(data.severity || 'INFO').toUpperCase();
  const imageSrc = getImageUrl(data.image_url);
  const summary = alertSummary(data);
  const hasEvidence = typeof data.evidence_id === 'number' && data.evidence_id > 0;
  const severityLabel: Record<string, string> = {
    CRITICAL: '紧急', WARNING: '警告', INFO: '提示',
  };
  const tone = severity === 'CRITICAL' ? 'text-red-300' : severity === 'WARNING' ? 'text-amber-300' : 'text-sky-300';
  return (
    <button
      type="button"
      disabled={!hasEvidence}
      onClick={() => hasEvidence && onOpenEvidence(data.evidence_id!)}
      aria-label={`${summary}，${hasEvidence ? '查看数据库详情' : '暂无数据库记录'}`}
      className="w-full text-left bg-zinc-900 border border-white/15 p-3 rounded-xl enabled:cursor-pointer enabled:hover:border-white/60 focus-visible:outline-2 focus-visible:outline-white focus-visible:outline-offset-2 transition-colors"
    >
      <span className="flex items-center justify-between gap-2 mb-2 text-xs">
        <span className={`font-bold ${tone}`}>{severityLabel[severity] || '提示'}</span>
        <span className="text-slate-400 tabular-nums">
          {Number.isFinite(Date.parse(data.timestamp)) ? new Date(data.timestamp).toLocaleTimeString('zh-CN', { hour12: false }) : '时间未知'}
        </span>
      </span>
      <span className="flex gap-3 items-center">
        {imageSrc && <img src={imageSrc} alt="告警现场截图" className="w-12 h-12 rounded object-cover shrink-0" />}
        <span className="text-sm font-bold text-white break-words leading-5">{summary}</span>
      </span>
      <span className="flex flex-wrap items-center justify-between gap-2 mt-2 text-xs text-slate-400">
        <span>{(data.repeat_count ?? 1) > 1 ? `累计 ${data.repeat_count} 次` : ''}</span>
        <span>{hasEvidence ? ((data.repeat_count ?? 1) > 1 ? '最新详情 →' : '查看详情 →') : '暂无数据库记录'}</span>
      </span>
    </button>
  );
}
