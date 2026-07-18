import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './AdminUi'

function DialogHarness({ onConfirm = vi.fn() }: { onConfirm?: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>打开确认框</button>
      <ConfirmDialog
        open={open}
        title="确认操作"
        description="这是操作说明"
        confirmText="确认"
        onCancel={() => setOpen(false)}
        onConfirm={onConfirm}
      />
    </>
  )
}

describe('ConfirmDialog', () => {
  it('has dialog semantics, closes with Escape, and restores focus', async () => {
    render(<DialogHarness />)
    const opener = screen.getByRole('button', { name: '打开确认框' })
    opener.focus()
    fireEvent.click(opener)

    const dialog = screen.getByRole('dialog', { name: '确认操作' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '取消' })).toHaveFocus()
    })

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })
})
