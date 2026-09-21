import { act, cleanup, render, renderHook, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { EvidencePanel } from './EvidencePanel';
import { useEvidence } from '../../hooks/useEvidence';

const record = (id: number) => ({ evidence_id: id, event_type: 'AI_DETECTION', severity: 'WARNING', message: `现场告警 ${id}`, created_at: '2026-09-14T08:00:00Z' });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('进入档案库即加载列表，新告警到达后刷新，无需点击告警', async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [record(1), record(2)] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [record(3), record(1), record(2)] }) });
  vi.stubGlobal('fetch', fetchMock);
  function Archive({ latestEvidenceId }: { latestEvidenceId?: number }) {
    return <EvidencePanel evidence={useEvidence()} latestEvidenceId={latestEvidenceId} />;
  }
  const view = render(<Archive />);
  expect(await screen.findByText('现场告警 1')).toBeInTheDocument();
  expect(screen.getByText('现场告警 2')).toBeInTheDocument();
  view.rerender(<Archive latestEvidenceId={3} />);
  expect(await screen.findByText('现场告警 3')).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(fetchMock.mock.calls.every(([url]) => String(url).endsWith('/api/v1/evidence'))).toBe(true);
});

it('列表刷新不覆盖详情错误，也不提前结束列表加载', async () => {
  let resolveList!: (response: unknown) => void;
  vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/123')
    ? Promise.resolve({ ok: false, status: 404 })
    : new Promise((resolve) => { resolveList = resolve; })));
  const { result } = renderHook(() => useEvidence());
  let pending!: Promise<void>;
  act(() => { pending = result.current.fetchEvidence(); });
  await act(() => result.current.openEvidence(123));
  expect(result.current.evidenceLoading).toBe(true);
  expect(result.current.detailError).toBe('告警记录不存在或已删除');
  await act(async () => {
    resolveList({ ok: true, json: async () => ({ items: [record(2)] }) });
    await pending;
  });
  expect(result.current.evidenceItems).toHaveLength(1);
  expect(result.current.detailError).toBe('告警记录不存在或已删除');
  expect(result.current.evidenceError).toBeNull();
});

it('较旧的列表响应不能覆盖新告警刷新后的结果', async () => {
  let resolveOld!: (response: unknown) => void;
  vi.stubGlobal('fetch', vi.fn()
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValueOnce({ ok: true, json: async () => ({ items: [record(3)] }) }));
  const { result } = renderHook(() => useEvidence());
  let old!: Promise<void>;
  act(() => { old = result.current.fetchEvidence(); });
  await act(() => result.current.fetchEvidence());
  await act(async () => {
    resolveOld({ ok: true, json: async () => ({ items: [] }) });
    await old;
  });
  expect(result.current.evidenceItems.map((item) => item.evidence_id)).toEqual([3]);
});
