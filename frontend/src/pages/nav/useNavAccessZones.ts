import { useCallback, useEffect, useRef, useState } from 'react'
import { mapAccessApi, type MapAccessZone, type MapPoint } from '../../api/mapAccessApi'

export function useNavAccessZones(sceneId: string | null, canRead: boolean, canManage: boolean, onLog: (message: string, level?: 'info' | 'error') => void) {
  const [zones, setZones] = useState<MapAccessZone[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [editingId, setEditingId] = useState<number | undefined>()
  const [name, setName] = useState('')
  const [level, setLevel] = useState('1')
  const [enabled, setEnabled] = useState(true)
  const [margin, setMargin] = useState(.15)
  const [draft, setDraft] = useState<MapPoint[]>([])
  const [drawing, setDrawing] = useState(false)
  const generation = useRef(0)
  const busy = useRef(false)
  const cancel = useCallback(() => {
    setEditingId(undefined); setDraft([]); setDrawing(false); setName(''); setError('')
  }, [])
  useEffect(() => {
    const request = ++generation.current
    setZones([]); cancel(); setLoading(Boolean(sceneId && canRead))
    if (sceneId && canRead) {
      void mapAccessApi.zones(sceneId).then(items => {
        if (request === generation.current) setZones(items)
      }).catch(e => { if (request === generation.current) setError(e instanceof Error ? e.message : '区域加载失败') })
        .finally(() => { if (request === generation.current) setLoading(false) })
    }
    return () => { generation.current += 1 }
  }, [sceneId, canRead, cancel])
  useEffect(() => { if (!canManage) cancel() }, [canManage, cancel])
  const create = () => {
    if (!canManage || busy.current) return
    setEditingId(undefined); setName(`区域${zones.length + 1}`); setLevel('1'); setEnabled(true); setMargin(.15); setDraft([]); setDrawing(true); setError('')
  }
  const edit = (zone: MapAccessZone) => {
    if (!canManage || busy.current) return
    setEditingId(zone.id); setName(zone.name); setLevel(zone.access_level ? String(zone.access_level) : '')
    setEnabled(Boolean(zone.enabled)); setMargin(zone.boundary_margin_m)
    setDraft(zone.vertices.map(([x, y, z]) => ({ x, y, z }))); setDrawing(false); setError('')
  }
  const addPoint = (point: MapPoint) => {
    if (canManage && drawing && !busy.current) setDraft(items => [...items, point])
  }
  const save = async () => {
    if (!canManage || busy.current || !sceneId || draft.length < 3 || !name.trim() || !['1', '2', '3'].includes(level)) return
    const request = generation.current
    busy.current = true; setSaving(true); setError('')
    try {
      await mapAccessApi.save({ scene_id: sceneId, name: name.trim(), access_level: Number(level), enabled, boundary_margin_m: margin, vertices: draft }, editingId)
      const items = await mapAccessApi.zones(sceneId)
      if (request === generation.current) { setZones(items); cancel(); onLog('区域名称、级别和边界已保存并生效') }
    } catch (e) { if (request === generation.current) setError(e instanceof Error ? e.message : '保存区域失败') }
    finally { busy.current = false; setSaving(false) }
  }
  const remove = async (id: number) => {
    if (!canManage || busy.current || !sceneId) return
    const request = generation.current
    busy.current = true; setSaving(true); setError('')
    try {
      await mapAccessApi.remove(id)
      const items = await mapAccessApi.zones(sceneId)
      if (request === generation.current) { setZones(items); if (editingId === id) cancel(); onLog('区域已删除') }
    } catch (e) { if (request === generation.current) setError(e instanceof Error ? e.message : '删除区域失败') }
    finally { busy.current = false; setSaving(false) }
  }
  return { zones, loading, saving, error, editingId, name, setName, level, setLevel, enabled, setEnabled, margin, setMargin, draft, setDraft, drawing, setDrawing, create, edit, addPoint, save, remove, cancel }
}
export type NavAccessZoneEditor = ReturnType<typeof useNavAccessZones>
