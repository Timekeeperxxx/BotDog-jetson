import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '../../api/apiFetch'
import { CameraControlPanel } from './CameraControlPanel'

vi.mock('../../api/apiFetch', () => ({ apiFetch: vi.fn() }))
const auth = vi.hoisted(() => ({ operator: true }))
vi.mock('../../stores/authStore', () => ({
  useAuthState: vi.fn(), hasAuthSession: () => true, hasRole: () => auth.operator,
}))
const status = { connected:true, mode:'head_follow', relative_pitch_deg:0, relative_yaw_deg:0 }
const jogs = () => vi.mocked(apiFetch).mock.calls.filter(([path]) => path === '/api/v1/gimbal/jog')

describe('camera panel keyboard scope', () => {
  beforeEach(() => { auth.operator=true; vi.mocked(apiFetch).mockReset().mockResolvedValue(status) })

  it('accepts arrow keys when open and stops when the panel closes', async () => {
    const {rerender} = render(<CameraControlPanel open onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByTitle('向上点动')).toBeEnabled())
    fireEvent.keyDown(window,{key:'ArrowUp'})
    await waitFor(() => expect(jogs()).toHaveLength(1))
    expect(JSON.parse(String(jogs()[0][1]?.body))).toEqual({pitch_velocity_dps:12,yaw_velocity_dps:0})
    rerender(<CameraControlPanel open={false} onClose={vi.fn()} />)
    await waitFor(() => expect(jogs()).toHaveLength(2))
    expect(JSON.parse(String(jogs()[1][1]?.body))).toEqual({pitch_velocity_dps:0,yaw_velocity_dps:0})
  })

  it('keeps clicking a direction as a normal timed jog', async () => {
    render(<CameraControlPanel open onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByTitle('向左点动')).toBeEnabled())
    fireEvent.click(screen.getByTitle('向左点动'))
    await waitFor(() => expect(jogs()).toHaveLength(1))
    expect(JSON.parse(String(jogs()[0][1]?.body))).toEqual({pitch_velocity_dps:0,yaw_velocity_dps:-12})
  })

  it('does not capture slider keys, or arrow keys while closed', async () => {
    const {rerender} = render(<CameraControlPanel open onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByTitle('向上点动')).toBeEnabled())
    fireEvent.keyDown(screen.getAllByRole('slider')[0],{key:'ArrowUp'})
    rerender(<CameraControlPanel open={false} onClose={vi.fn()} />)
    fireEvent.keyDown(window,{key:'ArrowUp'})
    expect(jogs()).toHaveLength(0)
  })

  it('does not send camera commands for a viewer or disconnected device', async () => {
    auth.operator=false
    const {rerender} = render(<CameraControlPanel open onClose={vi.fn()} />)
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith('/api/v1/gimbal/status'))
    fireEvent.keyDown(window,{key:'ArrowLeft'})
    expect(jogs()).toHaveLength(0)
    auth.operator=true
    vi.mocked(apiFetch).mockResolvedValue({...status,connected:false})
    rerender(<CameraControlPanel open={false} onClose={vi.fn()} />)
    rerender(<CameraControlPanel open onClose={vi.fn()} />)
    await waitFor(() => expect(screen.getByText('云台未连接')).toBeInTheDocument())
    fireEvent.keyDown(window,{key:'ArrowLeft'})
    expect(jogs()).toHaveLength(0)
  })
})
