import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { NavAccessZonesPanel } from './NavAccessZonesPanel'
import { useNavAccessZones } from './useNavAccessZones'

const api = vi.hoisted(() => ({ zones: vi.fn(), save: vi.fn(), remove: vi.fn() }))
vi.mock('../../api/mapAccessApi', () => ({ mapAccessApi: api }))
afterEach(() => vi.clearAllMocks())
function Harness({ scene = 'Scene01_Test', canManage = true }) {
  const editor = useNavAccessZones(scene, true, canManage, vi.fn())
  return <><NavAccessZonesPanel editor={editor} canManage={canManage} />{[[0,0],[4,0],[4,4]].map(([x,y],i) => <button key={i} onClick={() => editor.addPoint({x,y,z:.4})}>地图点{i+1}</button>)}</>
}
it('saves region name and level from navigation with actual selected map vertices', async () => {
  api.zones.mockResolvedValue([]); api.save.mockResolvedValue({id:1})
  render(<Harness />)
  const create = await screen.findByRole('button', {name:'新建区域'})
  await waitFor(() => expect(create).toBeEnabled())
  fireEvent.click(create)
  fireEvent.change(screen.getByLabelText('区域名称'),{target:{value:'区域2'}})
  fireEvent.change(screen.getByLabelText('区域级别'),{target:{value:'2'}})
  for(let i=1;i<=3;i++) fireEvent.click(screen.getByRole('button',{name:`地图点${i}`}))
  fireEvent.click(screen.getByRole('button',{name:'保存区域'}))
  await waitFor(() => expect(api.save).toHaveBeenCalledWith(expect.objectContaining({scene_id:'Scene01_Test',name:'区域2',access_level:2,vertices:[{x:0,y:0,z:.4},{x:4,y:0,z:.4},{x:4,y:4,z:.4}]}),undefined))
  expect(api.save.mock.calls[0][0]).not.toHaveProperty('authorized_identity_ids')
})
it('clears draft on scene switch and ignores a late previous-scene response', async () => {
  let complete: (v: unknown[]) => void = () => undefined
  api.zones.mockImplementationOnce(() => new Promise(resolve => { complete=resolve })).mockResolvedValue([])
  const {rerender}=render(<Harness />)
  rerender(<Harness scene="Scene02_Other" />)
  await waitFor(() => expect(screen.getByRole('button',{name:'新建区域'})).toBeEnabled())
  await act(async () => { complete([{id:1,name:'旧场景区域',vertices:[],enabled:true,access_level:1}]) })
  expect(screen.queryByText(/旧场景区域/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button',{name:'新建区域'}))
  fireEvent.click(screen.getByRole('button',{name:'地图点1'}))
  rerender(<Harness scene="Scene03_Other" />)
  await waitFor(() => expect(screen.queryByLabelText('区域名称')).not.toBeInTheDocument())
})
it('lets viewers see region levels without exposing editing controls', async () => {
  api.zones.mockResolvedValue([{id:1,name:'区域1',access_level:1,enabled:true,vertices:[],boundary_margin_m:.15}])
  render(<Harness canManage={false} />)
  expect(await screen.findByText('区域1 · 1级')).toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'新建区域'})).not.toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'编辑 区域1'})).not.toBeInTheDocument()
})
