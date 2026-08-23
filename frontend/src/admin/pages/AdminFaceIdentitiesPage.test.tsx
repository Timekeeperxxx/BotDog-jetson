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

  it('uploads a user-selected face photo group for the selected identity', async () => {
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

    const input = await screen.findByLabelText('上传 张三 的人脸图组')
    const frontPhoto = new File(['front-face'], 'zhang-san-front.png', { type: 'image/png' })
    const sidePhoto = new File(['side-face'], 'zhang-san-left.png', { type: 'image/png' })
    fireEvent.change(input, { target: { files: [frontPhoto, sidePhoto] } })

    await waitFor(() => expect(api.addTemplate).toHaveBeenNthCalledWith(1, 7, frontPhoto))
    await waitFor(() => expect(api.addTemplate).toHaveBeenNthCalledWith(2, 7, sidePhoto))
  })

  it('does not delete a template when its metadata is clicked and requires confirmation', async () => {
    api.list.mockResolvedValue([{
      id: 1, display_name: '测试人员A', notes: null, enabled: true,
      created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z',
      templates: [{ id: 2, identity_id: 1, dimension: 128, model_name: 'OpenCV SFace', model_version: '2021dec', quality: 0.91, created_at: '2026-08-10T00:00:00Z' }],
    }])
    api.status.mockResolvedValue({
      enabled: true, available: true, engine_loaded: true, model_name: 'OpenCV SFace',
      detect_model_path: '/models/yunet.onnx', recognition_model_path: '/models/sface.onnx',
      identity_count: 1, template_count: 1, match_threshold: 0.45, last_reload_at: null, error: null,
    })
    api.deleteTemplate.mockResolvedValue(undefined)

    render(<AdminFaceIdentitiesPage />)

    const metadata = await screen.findByText(/模板 #2/)
    fireEvent.click(metadata)
    expect(api.deleteTemplate).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '删除 测试人员A 的模板 #2' }))
    expect(screen.getByRole('dialog', { name: '删除人脸模板' })).toBeInTheDocument()
    expect(api.deleteTemplate).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: '确认删除模板' }))
    await waitFor(() => expect(api.deleteTemplate).toHaveBeenCalledWith(1, 2))
  })
})
