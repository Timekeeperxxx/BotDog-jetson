import { useEffect, useMemo, useRef, useState, type DragEvent } from 'react'
import { BrainCircuit, Download, FileImage, LoaderCircle, RefreshCw, Upload, X } from 'lucide-react'
import {
  modelTesterApi,
  type ModelTestOption,
  type ModelTestRunResult,
} from '../../api/modelTesterApi'
import { AdminCard, EmptyState, StatusBadge, ToolbarButton } from '../AdminUi'

type PreviewResult = ModelTestRunResult & { previewUrl: string }

const ACCEPTED_EXTENSIONS = new Set([
  'jpg', 'jpeg', 'png', 'bmp', 'webp',
  'mp4', 'avi', 'mov', 'mkv', 'm4v', 'webm',
])
const VIDEO_EXTENSIONS = new Set(['mp4', 'avi', 'mov', 'mkv', 'm4v', 'webm'])

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(seconds: number) {
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`
  return `${seconds.toFixed(2)} 秒`
}

export function AdminModelTesterPage() {
  const [models, setModels] = useState<ModelTestOption[]>([])
  const [selectedModel, setSelectedModel] = useState('helmet')
  const [confidence, setConfidence] = useState(0.35)
  const [videoFps, setVideoFps] = useState(5)
  const [file, setFile] = useState<File | null>(null)
  const [maxUploadBytes, setMaxUploadBytes] = useState(512 * 1024 * 1024)
  const [resultTtlSeconds, setResultTtlSeconds] = useState(7 * 24 * 60 * 60)
  const [loadingModels, setLoadingModels] = useState(true)
  const [running, setRunning] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<PreviewResult | null>(null)
  const [playbackError, setPlaybackError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadModels = async () => {
    setLoadingModels(true)
    setError(null)
    try {
      const response = await modelTesterApi.listModels()
      setModels(response.items)
      setMaxUploadBytes(response.max_upload_bytes)
      setResultTtlSeconds(response.result_ttl_seconds)
      setSelectedModel((current) => {
        const currentAvailable = response.items.some((item) => item.key === current && item.available)
        return currentAvailable ? current : response.items.find((item) => item.available)?.key ?? current
      })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型状态加载失败')
    } finally {
      setLoadingModels(false)
    }
  }

  useEffect(() => { void loadModels() }, [])

  useEffect(() => () => {
    if (result?.previewUrl && typeof URL.revokeObjectURL === 'function') {
      URL.revokeObjectURL(result.previewUrl)
    }
  }, [result])

  const selectedModelInfo = useMemo(
    () => models.find((item) => item.key === selectedModel) ?? null,
    [models, selectedModel],
  )
  const chooseModel = (modelKey: string) => {
    setSelectedModel(modelKey)
    setConfidence(modelKey === 'weapon' ? 0.65 : 0.35)
  }
  const isVideoFile = useMemo(() => {
    const extension = file?.name.split('.').pop()?.toLowerCase() ?? ''
    return VIDEO_EXTENSIONS.has(extension)
  }, [file])

  const chooseFile = (nextFile: File | null) => {
    if (!nextFile) return
    const extension = nextFile.name.split('.').pop()?.toLowerCase() ?? ''
    if (!ACCEPTED_EXTENSIONS.has(extension)) {
      setError('不支持该文件格式，请选择图片或常见视频文件')
      return
    }
    if (nextFile.size > maxUploadBytes) {
      setError(`文件不能超过 ${formatBytes(maxUploadBytes)}`)
      return
    }
    setFile(nextFile)
    setError(null)
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragging(false)
    chooseFile(event.dataTransfer.files.item(0))
  }

  const runTest = async () => {
    if (!file) {
      setError('请先选择一张图片或一段视频')
      return
    }
    if (!selectedModelInfo?.available) {
      setError('所选模型当前不可用')
      return
    }

    setRunning(true)
    setError(null)
    try {
      const runResult = await modelTesterApi.run(file, selectedModel, confidence, videoFps)
      const blob = await modelTesterApi.getResult(runResult.result_url)
      const previewUrl = URL.createObjectURL(blob)
      setPlaybackError(null)
      setResult({ ...runResult, previewUrl })
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '模型测试失败')
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="space-y-6">
      <AdminCard
        title="模型测试"
        subtitle="上传图片或视频，使用设备上的模型执行一次离线推理；不会触发告警、跟踪或机器人动作。"
        actions={(
          <ToolbarButton onClick={() => void loadModels()} disabled={loadingModels || running}>
            <RefreshCw size={14} className="mr-1.5 inline-block" />
            {loadingModels ? '检查中' : '检查模型'}
          </ToolbarButton>
        )}
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {models.map((model) => (
            <button
              key={model.key}
              type="button"
              disabled={!model.available || running}
              onClick={() => chooseModel(model.key)}
              aria-pressed={selectedModel === model.key}
              className={`rounded-md border p-3 text-left transition-colors ${
                selectedModel === model.key
                  ? 'border-sky-500/70 bg-sky-500/10'
                  : 'border-white/8 bg-black/20 hover:border-white/20'
              } disabled:cursor-not-allowed disabled:opacity-55`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-white">{model.name}</span>
                <StatusBadge status={model.available ? 'normal' : 'failed'} />
              </div>
              <p className="mt-2 text-xs leading-5 text-zinc-400">{model.description}</p>
              <div className="mt-2 font-mono text-[11px] text-sky-400/80">{model.runtime}</div>
            </button>
          ))}
        </div>

        {!loadingModels && models.length === 0 ? (
          <EmptyState title="模型信息不可用" description="请检查后端服务和模型目录后重新加载。" />
        ) : null}

        <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
          <div
            onDragEnter={(event) => { event.preventDefault(); setDragging(true) }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            className={`flex min-h-40 items-center justify-center rounded-lg border border-dashed px-6 py-8 text-center transition-colors ${
              dragging ? 'border-sky-400 bg-sky-500/10' : 'border-white/15 bg-[#0d1014]'
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              aria-label="选择测试文件"
              className="hidden"
              accept="image/jpeg,image/png,image/bmp,image/webp,video/mp4,video/x-msvideo,video/quicktime,video/x-matroska,video/webm"
              disabled={running}
              onChange={(event) => {
                chooseFile(event.target.files?.item(0) ?? null)
                event.currentTarget.value = ''
              }}
            />
            {file ? (
              <div className="w-full">
                <FileImage size={30} className="mx-auto text-sky-400" />
                <div className="mt-3 truncate text-sm font-medium text-white" title={file.name}>{file.name}</div>
                <div className="mt-1 text-xs text-zinc-500">{formatBytes(file.size)} · 上传后原文件立即删除</div>
                <div className="mt-4 flex justify-center gap-2">
                  <ToolbarButton onClick={() => fileInputRef.current?.click()} disabled={running}>更换文件</ToolbarButton>
                  <ToolbarButton onClick={() => setFile(null)} disabled={running} ariaLabel="移除文件">
                    <X size={14} />
                  </ToolbarButton>
                </div>
              </div>
            ) : (
              <div>
                <Upload size={30} className="mx-auto text-zinc-500" />
                <div className="mt-3 text-sm font-medium text-zinc-200">拖放图片或视频到这里</div>
                <p className="mt-1 text-xs text-zinc-500">
                  JPG、PNG、BMP、WebP；MP4、AVI、MOV、MKV、WebM，最大 {formatBytes(maxUploadBytes)}
                </p>
                <button
                  type="button"
                  disabled={running}
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-4 rounded-md bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  选择文件
                </button>
              </div>
            )}
          </div>

          <div className="space-y-5 rounded-lg border border-white/8 bg-black/20 p-4">
            <label className="block text-sm text-zinc-300">
              检测模型
              <select
                value={selectedModel}
                disabled={running || loadingModels}
                onChange={(event) => chooseModel(event.target.value)}
                className="mt-2 w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none focus:border-sky-600 disabled:opacity-50"
              >
                {models.map((model) => (
                  <option key={model.key} value={model.key} disabled={!model.available}>
                    {model.name}{model.available ? '' : '（不可用）'}
                  </option>
                ))}
              </select>
            </label>

            {isVideoFile ? (
              <label className="block text-sm text-zinc-300">
                视频检测帧率
                <select
                  value={videoFps}
                  disabled={running}
                  onChange={(event) => setVideoFps(Number(event.target.value))}
                  className="mt-2 w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none focus:border-sky-600 disabled:opacity-50"
                >
                  <option value={2}>2 FPS（最快）</option>
                  <option value={5}>5 FPS（推荐）</option>
                  <option value={10}>10 FPS（更细致）</option>
                  <option value={30}>最高 30 FPS（最慢）</option>
                </select>
                <span className="mt-1 block text-xs leading-5 text-zinc-500">输出视频会基本保持原时长，并统一转为浏览器可播放的 H.264。</span>
              </label>
            ) : null}

            <label className="block text-sm text-zinc-300">
              <span className="flex items-center justify-between">
                <span>置信度阈值</span>
                <span className="font-mono text-sky-300">{confidence.toFixed(2)}</span>
              </span>
              <input
                type="range"
                min="0.05"
                max="0.95"
                step="0.05"
                value={confidence}
                disabled={running || selectedModel === 'weather'}
                onChange={(event) => setConfidence(Number(event.target.value))}
                className="mt-3 w-full accent-sky-500 disabled:opacity-40"
              />
              <span className="mt-1 block text-xs leading-5 text-zinc-500">
                {selectedModel === 'weather' ? '天气分类固定显示概率最高的 3 个类别。' : '阈值越高，保留的低置信度目标越少。'}
              </span>
            </label>

            <button
              type="button"
              onClick={() => void runTest()}
              disabled={running || !file || !selectedModelInfo?.available}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-sky-600 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
            >
              {running ? <LoaderCircle size={16} className="animate-spin" /> : <BrainCircuit size={16} />}
              {running ? '正在推理…' : '开始测试'}
            </button>
            <p className="text-xs leading-5 text-zinc-500">TensorRT 模型会优先使用 GPU；视频按所选帧率抽帧检测，识别累计不做跨帧去重。</p>
            {selectedModel === 'pose' ? (
              <p className="text-xs leading-5 text-amber-300/80">“疑似破坏围栏动作”只根据连续手腕动作判断；上传素材没有围栏标定和结构变化数据，因此不能视为确认告警。</p>
            ) : null}
          </div>
        </div>

        {error ? (
          <div role="alert" className="mt-5 rounded-md border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-300">{error}</div>
        ) : null}
      </AdminCard>

      {result ? (
        <AdminCard
          title="测试结果"
          subtitle={`由 ${result.model_name} 生成；结果文件约保留 ${Math.max(1, Math.round(resultTtlSeconds / 86400))} 天。`}
          actions={(
            <a
              href={result.previewUrl}
              download={result.filename}
              className="inline-flex items-center rounded-md border border-white/12 bg-[#1b2026] px-3 py-2 text-sm font-medium text-zinc-100 transition-colors hover:border-white/25 hover:bg-[#222831]"
            >
              <Download size={14} className="mr-1.5" /> 下载结果
            </a>
          )}
        >
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
            <ResultMetric label="模型 / 运行时" value={`${result.model_name} · ${result.runtime}`} />
            <ResultMetric label="检测画面 / 原始画面" value={`${result.frames} / ${result.source_frames}`} />
            <ResultMetric
              label="原始帧率 → 检测帧率"
              value={result.source_fps && result.processing_fps ? `${result.source_fps} → ${result.processing_fps} FPS` : '--'}
            />
            <ResultMetric label="识别结果累计" value={`${result.detections}`} />
            <ResultMetric label="推理耗时" value={formatDuration(result.elapsed_seconds)} />
          </div>
          {Object.keys(result.label_counts).length > 0 ? (
            <div className="mt-4 rounded-md border border-white/8 bg-black/20 p-3">
              <div className="text-xs font-medium text-zinc-400">状态 / 类别累计</div>
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.entries(result.label_counts)
                  .sort((left, right) => right[1] - left[1])
                  .map(([label, count]) => (
                    <span key={label} className="rounded border border-sky-500/20 bg-sky-500/10 px-2.5 py-1 text-xs text-sky-200">
                      {label} · {count}
                    </span>
                  ))}
              </div>
            </div>
          ) : null}
          <div className="mt-5 overflow-hidden rounded-lg border border-white/8 bg-black">
            {result.is_video ? (
              <video
                controls
                preload="metadata"
                src={result.previewUrl}
                onError={() => setPlaybackError('浏览器未能解码结果视频，请下载文件后检查。')}
                className="max-h-[68vh] w-full object-contain"
              >
                浏览器无法预览该视频，请下载结果查看。
              </video>
            ) : (
              <img src={result.previewUrl} alt="模型测试标注结果" className="max-h-[68vh] w-full object-contain" />
            )}
          </div>
          {playbackError ? <div role="alert" className="mt-3 text-sm text-red-300">{playbackError}</div> : null}
        </AdminCard>
      ) : null}
    </div>
  )
}

function ResultMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/8 bg-black/25 p-4">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="mt-1.5 truncate text-lg font-semibold text-white" title={value}>{value}</div>
    </div>
  )
}
