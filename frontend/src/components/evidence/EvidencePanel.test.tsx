import { act, cleanup, fireEvent, render, renderHook, screen } from '@testing-library/react';
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
  expect(fetchMock.mock.calls.every(([url]) => String(url).includes('/api/v1/evidence?offset=0&limit=50'))).toBe(true);
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

it('选择告警标签后重新查询，清除旧选择，后续分页继续保留标签', async () => {
  const labels=[{ value: 'E_POSE_VAULTING_SUSPECTED', label: '翻越', count: 60 },
    { value: 'E_POSE_CLIMBING_SUSPECTED', label: '攀爬', count: 2 }];
  const vault=(id: number) => ({ ...record(id), event_code: 'E_POSE_VAULTING_SUSPECTED', alert_label: '翻越', message: `翻越记录 ${id}` });
  const fetchMock=vi.fn(async (url: string) => {
    const params=new URL(String(url), 'http://localhost').searchParams;
    const selected=params.get('label') === 'E_POSE_VAULTING_SUSPECTED';
    const more=params.get('offset') === '50';
    const items=selected ? Array.from({ length: more ? 10 : 50 }, (_, i) => vault((more ? 1050 : 1000) + i)) : [record(1),record(2)];
    return { ok: true, json: async () => ({ items, labels, has_more: selected && !more }) };
  });
  vi.stubGlobal('fetch',fetchMock);
  function Archive() { return <EvidencePanel evidence={useEvidence()} />; }
  render(<Archive />);
  expect(await screen.findByText('现场告警 1')).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('选择记录 1'));
  expect(screen.getByText('删除选中(1)')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('告警标签'), { target: { value: 'E_POSE_VAULTING_SUSPECTED' } });
  expect(await screen.findByText('翻越记录 1000')).toBeInTheDocument();
  expect(screen.queryByText('现场告警 1')).not.toBeInTheDocument();
  expect(screen.getByText('删除选中(0)')).toBeDisabled();
  fireEvent.click(screen.getByText('加载更多抓拍'));
  expect(await screen.findByText('翻越记录 1059')).toBeInTheDocument();
  expect(new URL(fetchMock.mock.calls.at(-1)![0], 'http://localhost').searchParams.get('label')).toBe('E_POSE_VAULTING_SUSPECTED');
  expect(screen.queryByText('加载更多抓拍')).not.toBeInTheDocument();
});

it('标签切换后的迟到列表不能覆盖新标签结果，关键词也发送给后端', async () => {
  let resolveOld!: (response: unknown) => void;
  const fetchMock=vi.fn()
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld=resolve; }))
    .mockResolvedValue({ ok: true, json: async () => ({ items: [record(7)], has_more: false }) });
  vi.stubGlobal('fetch',fetchMock);
  const { result }=renderHook(() => useEvidence());
  let old!: Promise<void>;
  act(() => { old=result.current.fetchEvidence(); });
  act(() => { result.current.setEvidenceLabel('E_POSE_VAULTING_SUSPECTED'); result.current.setSearchQuery('演示'); });
  await act(() => result.current.fetchEvidence());
  const params=new URL(fetchMock.mock.calls.at(-1)![0], 'http://localhost').searchParams;
  expect(params.get('label')).toBe('E_POSE_VAULTING_SUSPECTED');
  expect(params.get('q')).toBe('演示');
  await act(async () => { resolveOld({ ok:true,json:async () => ({items:[record(99)]}) }); await old; });
  expect(result.current.evidenceItems.map((item) => item.evidence_id)).toEqual([7]);
  expect(result.current.evidenceLoading).toBe(false);
});
