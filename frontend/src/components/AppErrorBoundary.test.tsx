import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

function BrokenPage(): never {
  throw new Error('test render failure')
}

describe('AppErrorBoundary', () => {
  it('shows a recoverable fallback when a page render fails', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})

    render(
      <AppErrorBoundary>
        <BrokenPage />
      </AppErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('页面发生异常')
    expect(screen.getByRole('button', { name: '刷新页面' })).toBeInTheDocument()
    consoleError.mockRestore()
  })
})
