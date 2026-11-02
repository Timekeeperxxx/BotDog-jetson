import { useState } from 'react'
import type { NavAccessZoneEditor } from './useNavAccessZones'

export function NavAccessZonesPanel({ editor: e, canManage }: { editor: NavAccessZoneEditor; canManage: boolean }) {
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const editing = e.draft.length > 0 || e.drawing || e.editingId !== undefined
  const button = 'rounded border border-white/20 px-2 py-1.5 text-xs hover:bg-white/10 disabled:opacity-40'
  return <section aria-label="区域设置" className="min-h-0 w-full overflow-y-auto p-3 text-sm text-zinc-200">
    <div className="mb-3 flex items-center justify-between gap-2"><h3 className="font-semibold">区域设置</h3>{canManage && <button className={button} disabled={e.saving || e.loading} onClick={e.create}>新建区域</button>}</div>
    {e.error && <p role="alert" className="mb-3 text-red-300">{e.error}</p>}
    {e.loading ? <p>正在加载区域…</p> : <div className="space-y-2">{e.zones.map(z => <div key={z.id} className="rounded border border-white/10 p-2">
      <p>{z.name} · {z.access_level ? `${z.access_level}级` : '未设置级别'}{z.enabled ? '' : ' · 已停用'}</p>
      {canManage && <div className="mt-2 flex gap-2"><button aria-label={`编辑 ${z.name}`} className={button} disabled={e.saving} onClick={() => e.edit(z)}>编辑</button><button aria-label={`删除 ${z.name}`} className={button} disabled={e.saving} onClick={() => setDeleteId(z.id)}>删除</button></div>}
      {deleteId === z.id && <div role="alert" className="mt-2"><p>确认删除 {z.name}？</p><button className={button} disabled={e.saving} onClick={() => { setDeleteId(null); void e.remove(z.id) }}>确认删除</button> <button className={button} onClick={() => setDeleteId(null)}>取消删除</button></div>}
    </div>)}{e.zones.length === 0 && <p className="text-xs text-zinc-400">暂无区域</p>}</div>}
    {canManage ? <>
      {editing && <div className="mt-3 space-y-3 border-t border-white/10 pt-3">
        <label className="block">区域名称<input aria-label="区域名称" value={e.name} onChange={v => e.setName(v.target.value)} disabled={e.saving} className="mt-1 w-full rounded bg-zinc-900 p-2" /></label>
        <label className="block">区域级别<select aria-label="区域级别" value={e.level} onChange={v => e.setLevel(v.target.value)} disabled={e.saving} className="mt-1 w-full rounded bg-zinc-900 p-2"><option value="" disabled>请选择级别</option><option value="1">1级</option><option value="2">2级</option><option value="3">3级</option></select></label>
        <label className="block"><input type="checkbox" checked={e.enabled} onChange={v => e.setEnabled(v.target.checked)} disabled={e.saving} /> 启用此区域</label>
        <label className="block">边界缓冲（米）<input aria-label="边界待判带" type="number" min={0} max={5} step={.05} value={e.margin} onChange={v => e.setMargin(Number(v.target.value))} disabled={e.saving} className="mt-1 w-full rounded bg-zinc-900 p-2" /></label>
        <p className="text-xs text-sky-200">{e.drawing ? '点击地图选点 · ' : ''}已选 {e.draft.length} 点</p>
        <div className="flex flex-wrap gap-2"><button className={button} disabled={e.saving} onClick={() => e.setDrawing(!e.drawing)}>{e.drawing ? '结束选点' : '继续选点'}</button><button className={button} disabled={e.saving || !e.draft.length} onClick={() => e.setDraft(v => v.slice(0, -1))}>撤销末点</button><button className={button} disabled={e.saving} onClick={() => { e.setDraft([]); e.setDrawing(true) }}>重画边界</button></div>
        <div className="flex gap-2"><button className={button} disabled={e.saving || !e.name.trim() || e.draft.length < 3 || !e.level} onClick={() => void e.save()}>{e.saving ? '保存中…' : '保存区域'}</button><button className={button} disabled={e.saving} onClick={e.cancel}>取消编辑</button></div>
      </div>}
    </> : null}
  </section>
}
