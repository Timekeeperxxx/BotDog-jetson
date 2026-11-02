import { apiFetch } from './apiFetch'

export type MapPoint = { x: number; y: number; z: number }
export type MapAccessZone = {
  id: number; scene_id: string; name: string; access_level: number | null
  vertices: number[][]; enabled: boolean; boundary_margin_m: number
}
export type ZoneWrite = { scene_id: string; name: string; access_level: number; vertices: MapPoint[]; enabled: boolean; boundary_margin_m: number }
export type AccessStatus = {
  calibration_required: boolean; method: string; detail: string; enabled_zone_count: number
  last_decisions: { status: string; reason: string; display_name?: string; track_id?: number; zones: { name: string }[] }[]
}
export const mapAccessApi = {
  zones: (scene?: string) => apiFetch<MapAccessZone[]>(`/api/v1/map-access/zones${scene ? `?scene_id=${encodeURIComponent(scene)}` : ''}`),
  save: (data: ZoneWrite, id?: number) => apiFetch<MapAccessZone>(`/api/v1/map-access/zones${id ? `/${id}` : ''}`, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(data) }),
  remove: (id: number) => apiFetch(`/api/v1/map-access/zones/${id}`, { method:'DELETE' }),
  status: () => apiFetch<AccessStatus>('/api/v1/map-access/status'),
}
