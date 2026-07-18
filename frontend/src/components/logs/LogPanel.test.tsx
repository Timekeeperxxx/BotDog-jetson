import { render, screen, within } from '@testing-library/react';
import { createRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import type { LogEntry } from '../../hooks/useBotDogWebSocket';
import { LogPanel, MAX_VISIBLE_LOGS } from './LogPanel';

function buildLogs(count: number): LogEntry[] {
  return Array.from({ length: count }, (_, index) => ({
    timestamp: 1_700_000_000 + index,
    level: index % 2 === 0 ? 'info' : 'error',
    module: 'WHEP',
    message: `日志-${index}`,
  }));
}

describe('LogPanel', () => {
  it('只渲染最近的日志，并在固定高度区域内滚动', () => {
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
    const logs = buildLogs(MAX_VISIBLE_LOGS + 5);

    render(
      <LogPanel
        logs={logs}
        isExpanded
        onToggle={vi.fn()}
        sidebarLogEndRef={createRef<HTMLDivElement>()}
      />,
    );

    const panel = screen.getByRole('region', { name: '终端状态日志' });
    const logArea = screen.getByRole('log');

    expect(panel).toHaveClass('overflow-hidden', 'h-64', 'max-h-[40%]');
    expect(logArea).toHaveClass('overflow-y-auto', 'min-h-0');
    expect(logArea.querySelectorAll('[data-log-entry]')).toHaveLength(MAX_VISIBLE_LOGS);
    expect(within(logArea).queryByText(/日志-4$/)).not.toBeInTheDocument();
    expect(within(logArea).getByText(/日志-5$/)).toBeInTheDocument();
    expect(within(logArea).getByText(/日志-24$/)).toBeInTheDocument();
  });
});
