import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PoseActionWarning } from './PoseActionWarning';
afterEach(() => vi.useRealTimers());
it('keeps each warning while active and for one second after ending, including resumption', () => {
  vi.useFakeTimers();
  const damage='POSE_DAMAGE_SUSPECTED', climb='POSE_CLIMBING_SUSPECTED';
  const { rerender }=render(<PoseActionWarning actions={[damage,climb]} />);
  act(()=>vi.advanceTimersByTime(5000));
  expect(screen.getByText('疑似破坏动作')).toBeInTheDocument();
  rerender(<PoseActionWarning actions={[climb]} />);
  act(()=>vi.advanceTimersByTime(999));
  expect(screen.getByText('疑似破坏动作')).toBeInTheDocument();
  act(()=>vi.advanceTimersByTime(1));
  expect(screen.queryByText('疑似破坏动作')).not.toBeInTheDocument();
  expect(screen.getByText('疑似攀爬')).toBeInTheDocument();
  rerender(<PoseActionWarning actions={[]} />);
  act(()=>vi.advanceTimersByTime(500));
  rerender(<PoseActionWarning actions={[climb]} />);
  act(()=>vi.advanceTimersByTime(1000));
  expect(screen.getByText('疑似攀爬')).toBeInTheDocument();
  rerender(<PoseActionWarning />);
  act(()=>vi.advanceTimersByTime(1000));
  expect(screen.queryByText('疑似攀爬')).not.toBeInTheDocument();
});

it('shows vaulting and climbing separately and preserves each display hold', () => {
  vi.useFakeTimers();
  const vault='POSE_VAULTING_SUSPECTED', climb='POSE_CLIMBING_SUSPECTED';
  const { rerender }=render(<PoseActionWarning actions={[vault]} />);
  expect(screen.getByText('疑似翻越')).toBeInTheDocument();
  expect(screen.queryByText('疑似攀爬')).not.toBeInTheDocument();
  rerender(<PoseActionWarning actions={[climb]} />);
  expect(screen.getByText('疑似攀爬')).toBeInTheDocument();
  expect(screen.getByText('疑似翻越')).toBeInTheDocument();
  act(()=>vi.advanceTimersByTime(1000));
  expect(screen.queryByText('疑似翻越')).not.toBeInTheDocument();
  expect(screen.getByText('疑似攀爬')).toBeInTheDocument();
});
