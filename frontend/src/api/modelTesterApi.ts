import { apiFetch, apiFetchBlob } from './apiFetch'

export interface ModelTestOption {
  key: string
  name: string
  description: string
  available: boolean
  runtime: string
}

export interface ModelTestOptionsResponse {
  items: ModelTestOption[]
  max_upload_bytes: number
  result_ttl_seconds: number
}

export interface ModelTestRunResult {
  result_id: string
  filename: string
  result_url: string
  model_key: string
  model_name: string
  runtime: string
  is_video: boolean
  media_type: string
  frames: number
  source_frames: number
  source_fps: number | null
  processing_fps: number | null
  detections: number
  label_counts: Record<string, number>
  elapsed_seconds: number
}

export const modelTesterApi = {
  listModels(): Promise<ModelTestOptionsResponse> {
    return apiFetch('/api/v1/model-tester/models')
  },

  run(file: File, model: string, confidence: number, videoFps: number): Promise<ModelTestRunResult> {
    const form = new FormData()
    form.append('model', model)
    form.append('confidence', confidence.toFixed(2))
    form.append('video_fps', videoFps.toFixed(1))
    form.append('media', file)
    return apiFetch('/api/v1/model-tester/runs', {
      method: 'POST',
      body: form,
    })
  },

  getResult(resultUrl: string): Promise<Blob> {
    return apiFetchBlob(resultUrl)
  },
}
