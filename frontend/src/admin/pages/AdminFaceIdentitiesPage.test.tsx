import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AdminFaceIdentitiesPage } from './AdminFaceIdentitiesPage'

const api = vi.hoisted(() => ({
  list: vi.fn(), status: vi.fn(), create: vi.fn(), update: vi.fn(),
  delete: vi.fn(), addTemplate: vi.fn(), deleteTemplate: vi.fn(),
}))

vi.mock('../../api/faceIdentitiesApi', () => ({ faceIdentitiesApi: api }))

afterEach(() => vi.clearAllMocks())

describe('AdminFaceIdentitiesPage', () => {
  it('renders identities, template metadata and service status', async () => {
    api.list.mockResolvedValue([{
      id: 1, display_name: '测试人员A', notes: '门岗人员', enabled: true,
      created_at: '2026-08-04T00:00:00Z', updated_at: '2026-08-04T00:00:00Z',
      templates: [{ id: 2, identity_id: 1, dimension: 128, model_name: 'OpenCV SFace', model_version: '2021dec', quality: 0.91, created_at: '2026-08-04T00:00:00Z' }],
    }])
    api.status.mockResolvedValue({
      enabled: true, available: true, engine_loaded: true, model_name: 'OpenCV SFace',
      detect_model_path: '/models/yunet.onnx', recognition_model_path: '/models/sface.onnx',
      identity_count: 1, template_count: 1, match_threshold: 0.45, last_reload_at: null, error: null,
    })

    render(<AdminFaceIdentitiesPage />)

    await waitFor(() => expect(screen.getByText('测试人员A')).toBeInTheDocument())
    expect(screen.getByText('门岗人员')).toBeInTheDocument()
    expect(screen.getByText(/模板 #2/)).toBeInTheDocument()
    expect(screen.getByText('0.45')).toBeInTheDocument()
  })

  it('uploads a user-selected face photo for the selected identity', async () => {
    api.list.mockResolvedValue([{
      id: 7, display_name: '张三', notes: null, enabled: true,
      created_at: '2026-08-05T00:00:00Z', updated_at: '2026-08-05T00:00:00Z',
      templates: [],
    }])
    api.status.mockResolvedValue({
      enabled: true, available: true, engine_loaded: true, model_name: 'OpenCV SFace',
      detect_model_path: '/models/yunet.onnx', recognition_model_path: '/models/sface.onnx',
      identity_count: 0, template_count: 0, match_threshold: 0.45, last_reload_at: null, error: null,
    })
    api.addTemplate.mockResolvedValue({
      id: 9, identity_id: 7, dimension: 128, model_name: 'OpenCV SFace',
      model_version: '2021dec', quality: 0.9, created_at: '2026-08-05T00:00:00Z',
    })

    render(<AdminFaceIdentitiesPage />)

    const input = await screen.findByLabelText('上传正脸')
    const photo = new File(['face-image'], 'zhang-san.png', { type: 'image/png' })
    fireEvent.change(input, { target: { files: [photo] } })

    await waitFor(() => expect(api.addTemplate).toHaveBeenCalledWith(7, photo))
  })
})
