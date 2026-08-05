import { apiFetch } from './apiFetch'

export interface FaceTemplate {
  id: number
  identity_id: number
  dimension: number
  model_name: string
  model_version: string
  quality: number
  created_at: string
}

export interface FaceIdentity {
  id: number
  display_name: string
  notes: string | null
  enabled: boolean
  created_at: string
  updated_at: string
  templates: FaceTemplate[]
}

export interface FaceRecognitionStatus {
  enabled: boolean
  available: boolean
  engine_loaded: boolean
  model_name: string
  detect_model_path: string
  recognition_model_path: string
  identity_count: number
  template_count: number
  match_threshold: number
  last_reload_at: string | null
  error: string | null
}

export const faceIdentitiesApi = {
  list(): Promise<FaceIdentity[]> {
    return apiFetch('/api/v1/face-identities')
  },
  status(): Promise<FaceRecognitionStatus> {
    return apiFetch('/api/v1/face-recognition/status')
  },
  create(payload: { display_name: string; notes?: string | null; enabled?: boolean }): Promise<FaceIdentity> {
    return apiFetch('/api/v1/face-identities', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },
  update(identityId: number, payload: { display_name?: string; notes?: string | null; enabled?: boolean }): Promise<FaceIdentity> {
    return apiFetch(`/api/v1/face-identities/${identityId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  },
  delete(identityId: number): Promise<void> {
    return apiFetch(`/api/v1/face-identities/${identityId}`, { method: 'DELETE' })
  },
  addTemplate(identityId: number, image: File): Promise<FaceTemplate> {
    const form = new FormData()
    form.append('image', image)
    return apiFetch(`/api/v1/face-identities/${identityId}/templates`, {
      method: 'POST',
      body: form,
    })
  },
  deleteTemplate(identityId: number, templateId: number): Promise<void> {
    return apiFetch(`/api/v1/face-identities/${identityId}/templates/${templateId}`, {
      method: 'DELETE',
    })
  },
}
