import { AlertTriangle, ChevronDown, ChevronUp, Info, Terminal } from 'lucide-react';
import { useEffect, useMemo } from 'react';
import type { RefObject } from 'react';
import type { LogEntry } from '../../hooks/useBotDogWebSocket';

export const MAX_VISIBLE_LOGS = 20;

export interface LogPanelProps {
  logs: LogEntry[];
  isExpanded: boolean;
  onToggle: () => void;
  sidebarLogEndRef: RefObject<HTMLDivElement | null>;
}

export function LogPanel({ logs, isExpanded, onToggle, sidebarLogEndRef }: LogPanelProps) {
  useEffect(() => {
    if (isExpanded) sidebarLogEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs, isExpanded, sidebarLogEndRef]);

  const visibleLogs = useMemo(() => logs.slice(-MAX_VISIBLE_LOGS), [logs]);
  const errorCount = useMemo(() => visibleLogs.filter((log) => log.level === 'error').length, [visibleLogs]);
  const warningCount = useMemo(() => visibleLogs.filter((log) => log.level === 'warning').length, [visibleLogs]);
  const latestLog = visibleLogs.at(-1) ?? null;

  return (
    <section
      aria-label="终端状态日志"
      className={`min-h-0 shrink-0 overflow-hidden flex flex-col border-b border-white/20 transition-all duration-300 ${isExpanded ? 'h-64 max-h-[40%]' : 'h-10'}`}
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex h-10 w-full shrink-0 cursor-pointer items-center justify-between border-0 bg-zinc-900 px-3 text-left text-white transition-colors hover:bg-zinc-800"
        aria-expanded={isExpanded}
      >
        <div className="flex min-w-0 items-center gap-2 font-bold">
          <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${errorCount > 0 ? 'bg-red-500/15 text-red-400' : 'bg-sky-500/15 text-sky-300'}`}>
            <Terminal size={14} />
          </span>
          <div className="flex min-w-0 flex-col leading-none">
            <span className="text-[10px] font-black uppercase tracking-widest">运行日志</span>
            <span className={`mt-1 truncate text-[8px] font-medium ${latestLog?.level === 'error' ? 'text-red-300' : 'text-white/45'}`}>
              {latestLog ? `[${latestLog.module}] ${latestLog.message}` : '暂无日志'}
            </span>
          </div>
          <div className="ml-1 flex shrink-0 items-center gap-1">
            <span className="rounded bg-white/10 px-1.5 py-0.5 text-[8px] text-white/60">{visibleLogs.length}</span>
            {warningCount > 0 ? <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[8px] text-amber-300">{warningCount} 警告</span> : null}
            {errorCount > 0 ? <span className="rounded bg-red-500/15 px-1.5 py-0.5 text-[8px] text-red-300">{errorCount} 错误</span> : null}
          </div>
        </div>
        {isExpanded ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
      </button>
      {isExpanded && (
        <div
          role="log"
          aria-live="polite"
          className="custom-scrollbar min-h-0 flex-1 overflow-y-auto border-t border-white/10 bg-[#07090c] p-2 font-mono text-[10px]"
        >
          {visibleLogs.length > 0 ? visibleLogs.map((log, index) => {
            const levelStyle = log.level === 'error'
              ? 'border-red-500/70 bg-red-950/20'
              : log.level === 'warning'
                ? 'border-amber-400/70 bg-amber-950/15'
                : 'border-sky-400/45 bg-white/[0.025]';
            const badgeStyle = log.level === 'error'
              ? 'bg-red-500/15 text-red-300'
              : log.level === 'warning'
                ? 'bg-amber-500/15 text-amber-300'
                : 'bg-sky-500/15 text-sky-300';
            return (
              <div
                data-log-entry
                key={`${log.timestamp}-${index}`}
                className={`mb-1.5 border-l-2 px-2.5 py-2 ${levelStyle}`}
              >
                <div className="mb-1 flex items-center gap-1.5">
                  {log.level === 'error'
                    ? <AlertTriangle size={11} className="shrink-0 text-red-400" />
                    : <Info size={11} className={`shrink-0 ${log.level === 'warning' ? 'text-amber-300' : 'text-sky-300'}`} />}
                  <time className="shrink-0 text-[9px] text-slate-500">
                    {new Date(log.timestamp * 1000).toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </time>
                  <span className="min-w-0 truncate font-bold text-slate-300">{log.module}</span>
                  <span className={`ml-auto shrink-0 rounded px-1.5 py-0.5 text-[8px] font-black ${badgeStyle}`}>
                    {log.level === 'error' ? '错误' : log.level === 'warning' ? '警告' : '信息'}
                  </span>
                </div>
                <p className={`m-0 whitespace-pre-wrap break-words leading-relaxed ${log.level === 'error' ? 'text-red-100' : 'text-slate-200'}`}>
                  {log.message}
                </p>
              </div>
            );
          }) : (
            <div className="flex h-full min-h-24 items-center justify-center text-[10px] text-white/35">暂无运行日志</div>
          )}
          <div ref={sidebarLogEndRef} />
        </div>
      )}
    </section>
  );
}
