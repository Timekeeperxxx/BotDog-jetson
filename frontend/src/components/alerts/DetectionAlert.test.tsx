import { act, fireEvent, render, renderHook, screen, cleanup } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { DetectionAlert } from './DetectionAlert';
import { parseAlertEvent, mergeAlertEvent } from '../../hooks/alertEventPolicy';
import { useEvidence } from '../../hooks/useEvidence';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const timestamp = '2026-09-14T08:00:00Z';
const payload = { event_type: 'AI_DETECTION', event_code: 'E_AI_PERSON', message: '检测到目标: 陌生人', severity: 'critical', evidence_id: 123, confidence: null };

it('不把跟踪状态和空事件渲染为空白告警', () => {
  for (const msg_type of ['STRANGER_TARGET_LOCKED', 'AUTO_TRACK_STARTED', 'AUTO_TRACK_STOPPED', 'AUTO_TRACK_MANUAL_OVERRIDE']) {
    expect(parseAlertEvent({ msg_type, timestamp, payload: { track_id: 1 } })).toBeNull();
  }
  expect(parseAlertEvent({ msg_type: 'ALERT_RAISED', timestamp, payload: {} })).toBeNull();
});

it('显示简洁中文，合并后点击打开最新记录', () => {
  const old = parseAlertEvent({ msg_type: 'ALERT_RAISED', timestamp, payload })!;
  const open = vi.fn();
  render(<DetectionAlert data={mergeAlertEvent([old], { ...old, evidence_id: 124 })[0]} onOpenEvidence={open} />);
  expect(screen.getByText('紧急')).toBeInTheDocument();
  expect(screen.getByText('检测到人员')).toBeInTheDocument();
  expect(screen.queryByText(/陌生人/)).not.toBeInTheDocument();
  expect(screen.getByText(/累计 2 次/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button'));
  expect(open).toHaveBeenCalledWith(124);
});

it('没有数据库记录时明确提示且不误跳转', () => {
  const alert = parseAlertEvent({ msg_type: 'ALERT_RAISED', timestamp, payload: { ...payload, evidence_id: null } })!;
  render(<DetectionAlert data={alert} onOpenEvidence={vi.fn()} />);
  expect(screen.getByRole('button')).toBeDisabled();
  expect(screen.getByText('暂无数据库记录')).toBeInTheDocument();
});

it('按主键读取详情，删除后显示错误并清除旧详情', async () => {
  const record = { ...payload, created_at: timestamp };
  const fetchMock = vi.fn().mockResolvedValueOnce({ ok: true, json: async () => record })
    .mockResolvedValueOnce({ ok: false, status: 404 });
  vi.stubGlobal('fetch', fetchMock);
  const { result } = renderHook(() => useEvidence());
  await act(() => result.current.openEvidence(123));
  expect(fetchMock.mock.calls[0][0]).toContain('/api/v1/evidence/123');
  expect(result.current.lightboxItem).toEqual(record);
  await act(() => result.current.openEvidence(123));
  expect(result.current.lightboxItem).toBeNull();
  expect(result.current.evidenceError).toBe('告警记录不存在或已删除');
});
