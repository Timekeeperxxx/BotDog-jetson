import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch } from '../../api/apiFetch';
import { WeaponDetectionControl } from './WeaponDetectionControl';
vi.mock('../../api/apiFetch', () => ({ apiFetch: vi.fn() }));
const fetchMock = vi.mocked(apiFetch);
beforeEach(() => { fetchMock.mockReset(); window.localStorage.clear(); });
afterEach(cleanup);

describe('weapon detection control', () => {
  it('reads the actual board switch independently of saved hidden boxes', async () => {
    window.localStorage.setItem('botdog.ai-overlay-layers.v3', JSON.stringify({ weapon: false }));
    fetchMock.mockResolvedValue({ configs: { weapon_enabled: { value: true } } });
    render(<WeaponDetectionControl />);
    await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true'));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/config?category=ai');
  });
  it('keeps the old state until backend confirms the stop', async () => {
    let resolve!: (value: unknown) => void;
    fetchMock.mockResolvedValueOnce({ configs: { weapon_enabled: { value: 'true' } } });
    fetchMock.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    render(<WeaponDetectionControl />);
    await waitFor(() => expect(screen.getByRole('switch')).toBeEnabled());
    fireEvent.click(screen.getByRole('switch'));
    expect(screen.getByRole('switch')).toBeDisabled();
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
    const request = fetchMock.mock.calls[1];
    expect(request[0]).toBe('/api/v1/config');
    expect(JSON.parse(request[1]?.body as string)).toMatchObject({ key: 'weapon_enabled', value: false });
    resolve({ success: true, config: { value: false }, runtime_apply: { applied: true, message: '已关闭' } });
    await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false'));
  });
  it('shows failed application without claiming the detector stopped', async () => {
    fetchMock.mockResolvedValueOnce({ configs: { weapon_enabled: { value: true } } });
    fetchMock.mockResolvedValueOnce({ success: true, config: { value: false }, runtime_apply: { applied: false, message: '服务未运行' } });
    render(<WeaponDetectionControl />);
    await waitFor(() => expect(screen.getByRole('switch')).toBeEnabled());
    fireEvent.click(screen.getByRole('switch'));
    expect(await screen.findByRole('alert')).toHaveTextContent('服务未运行');
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });
  it('disables the switch when current state cannot be read', async () => {
    fetchMock.mockRejectedValue(new Error('网络连接失败'));
    render(<WeaponDetectionControl />);
    expect(await screen.findByRole('alert')).toHaveTextContent('网络连接失败');
    expect(screen.getByRole('switch')).toBeDisabled();
  });
});
