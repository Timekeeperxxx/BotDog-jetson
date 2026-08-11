import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AdminModelTesterPage } from './AdminModelTesterPage'

const modelTesterApiMock = vi.hoisted(() => ({
  listModels: vi.fn(),
  run: vi.fn(),
  getResult: vi.fn(),
}))

vi.mock('../../api/modelTesterApi', () => ({
  modelTesterApi: modelTesterApiMock,
}))

describe('AdminModelTesterPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    modelTesterApiMock.listModels.mockResolvedValue({
      items: [
        { key: 'helmet', name: '安全帽检测', description: '识别人、头部和安全帽', available: true, runtime: 'TensorRT' },
        { key: 'weather', name: '天气分类', description: '显示 Top-3', available: false, runtime: 'TensorRT' },
      ],
      max_upload_bytes: 1024 * 1024,
      result_ttl_seconds: 7 * 24 * 60 * 60,
    })
    modelTesterApiMock.run.mockResolvedValue({
      result_id: 'run-1',
      filename: 'run-1-helmet.jpg',
      result_url: '/api/v1/model-tester/results/run-1-helmet.jpg',
      model_key: 'helmet',
      model_name: '安全帽检测',
      runtime: 'TensorRT',
      is_video: false,
      media_type: 'image/jpeg',
      frames: 1,
      source_frames: 1,
      source_fps: null,
      processing_fps: null,
      detections: 2,
      label_counts: { 人员: 2 },
      elapsed_seconds: 0.42,
    })
    modelTesterApiMock.getResult.mockResolvedValue(new Blob(['result'], { type: 'image/jpeg' }))
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:model-test-result'),
      revokeObjectURL: vi.fn(),
    })
  })

  it('uploads media, runs the selected model and renders the result', async () => {
    const user = userEvent.setup()
    render(<AdminModelTesterPage />)

    await waitFor(() => expect(screen.getByText('识别人、头部和安全帽')).toBeInTheDocument())
    expect(screen.getByRole('option', { name: '天气分类（不可用）' })).toBeDisabled()

    const file = new File(['image-bytes'], 'worker.jpg', { type: 'image/jpeg' })
    await user.upload(screen.getByLabelText('选择测试文件'), file)
    await user.click(screen.getByRole('button', { name: '开始测试' }))

    await waitFor(() => expect(screen.getByText('测试结果')).toBeInTheDocument())
    expect(modelTesterApiMock.run).toHaveBeenCalledWith(file, 'helmet', 0.35, 5)
    expect(modelTesterApiMock.getResult).toHaveBeenCalledWith(
      '/api/v1/model-tester/results/run-1-helmet.jpg',
    )
    expect(screen.getByAltText('模型测试标注结果')).toHaveAttribute('src', 'blob:model-test-result')
    expect(screen.getByText('2')).toBeInTheDocument()
  })
})
