import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { disableFenceDetection, enableFenceDetection, getFenceDetectionStatus } from '../../api/fenceDetectionApi';
import { useAuthState } from '../../stores/authStore';
import type { FenceDetectionStatus } from '../../types/fenceDetection';
import { FenceActionControl } from './FenceActionControl';

vi.mock('../../api/fenceDetectionApi', () => ({
  disableFenceDetection: vi.fn(), enableFenceDetection: vi.fn(), getFenceDetectionStatus: vi.fn(),
}));
vi.mock('../../stores/authStore', () => ({ useAuthState: vi.fn() }));

const status = (enabled: boolean) => ({ enabled, state: enabled ? 'finding' : 'disabled' }) as FenceDetectionStatus;
const switchButton = () => screen.getByRole('switch', { name: '围栏动作识别' });
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(useAuthState).mockReturnValue({ role: 'operator' } as ReturnType<typeof useAuthState>);
  vi.mocked(getFenceDetectionStatus).mockResolvedValue(status(false));
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('home fence action control', () => {
  it('reads the existing fence switch and enables real detection through its API', async () => {
    vi.mocked(enableFenceDetection).mockResolvedValue(status(true));
    vi.mocked(getFenceDetectionStatus).mockResolvedValueOnce(status(false)).mockResolvedValue(status(true));
    render(<FenceActionControl />);
    expect(switchButton()).toBeDisabled();
    await waitFor(() => expect(switchButton()).toBeEnabled());
    expect(switchButton()).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(switchButton());
    await waitFor(() => expect(switchButton()).toHaveAttribute('aria-checked', 'true'));
    expect(enableFenceDetection).toHaveBeenCalledOnce();
    expect(disableFenceDetection).not.toHaveBeenCalled();
  });

  it('keeps enabled while disabling is pending and blocks duplicate clicks', async () => {
    let finish!: (next: FenceDetectionStatus) => void;
    vi.mocked(getFenceDetectionStatus).mockResolvedValueOnce(status(true)).mockResolvedValue(status(false));
    vi.mocked(disableFenceDetection).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    render(<FenceActionControl />);
    await waitFor(() => expect(switchButton()).toBeEnabled());
    fireEvent.click(switchButton()); fireEvent.click(switchButton());
    expect(switchButton()).toBeDisabled();
    expect(switchButton()).toHaveAttribute('aria-checked', 'true');
    expect(disableFenceDetection).toHaveBeenCalledOnce();
    await act(async () => finish(status(false)));
    await waitFor(() => expect(switchButton()).toHaveAttribute('aria-checked', 'false'));
  });

  it('retains the actual enabled state and shows a failed stop', async () => {
    vi.mocked(getFenceDetectionStatus).mockResolvedValue(status(true));
    vi.mocked(disableFenceDetection).mockRejectedValue(new Error('关闭围栏检测失败'));
    render(<FenceActionControl />);
    await waitFor(() => expect(switchButton()).toBeEnabled());
    fireEvent.click(switchButton());
    expect(await screen.findByRole('alert')).toHaveTextContent('关闭围栏检测失败');
    expect(switchButton()).toHaveAttribute('aria-checked', 'true');
  });

  it('syncs a change made by the navigation page on the next status poll', async () => {
    vi.useFakeTimers();
    let current = status(false);
    vi.mocked(getFenceDetectionStatus).mockImplementation(async () => current);
    render(<FenceActionControl />);
    await act(async () => {});
    expect(switchButton()).toHaveAttribute('aria-checked', 'false');
    current = status(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    expect(switchButton()).toHaveAttribute('aria-checked', 'true');
    current = status(false);
    await act(async () => { await vi.advanceTimersByTimeAsync(750); });
    expect(switchButton()).toHaveAttribute('aria-checked', 'false');
    expect(enableFenceDetection).not.toHaveBeenCalled();
    expect(disableFenceDetection).not.toHaveBeenCalled();
  });

  it('disables changes when state is unavailable', async () => {
    vi.mocked(getFenceDetectionStatus).mockRejectedValue(new Error('网络连接失败'));
    render(<FenceActionControl />);
    expect(await screen.findByRole('alert')).toHaveTextContent('网络连接失败');
    expect(switchButton()).toBeDisabled();
    fireEvent.click(switchButton());
    expect(enableFenceDetection).not.toHaveBeenCalled();
  });

  it('shows state to viewers without allowing them to change it', async () => {
    vi.mocked(useAuthState).mockReturnValue({ role: 'viewer' } as ReturnType<typeof useAuthState>);
    vi.mocked(getFenceDetectionStatus).mockResolvedValue(status(true));
    render(<FenceActionControl />);
    await waitFor(() => expect(switchButton()).toHaveAttribute('aria-checked', 'true'));
    expect(switchButton()).toBeDisabled();
    fireEvent.click(switchButton());
    expect(disableFenceDetection).not.toHaveBeenCalled();
  });
});
