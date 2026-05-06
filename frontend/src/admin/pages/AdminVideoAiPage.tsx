import { useMemo, useState } from 'react'
import { Camera, RefreshCw, Save } from 'lucide-react'
import type { SystemConfig } from '../../types/config'
import type { VideoSource } from '../../types/admin'
import type { AiConfigGroup } from '../adminTypes'
import { AdminCard, EmptyState, SearchInput, StatusBadge, TableCell, TableHead, ToolbarButton } from '../AdminUi'
import { hasAuthSession, hasRole, useAuthState } from '../../stores/authStore'

function inferSourceStatus(source: VideoSource) {
  if (!source.enabled) return 'degraded'
  if (source.whep_url || source.rtsp_url) return 'normal'
  return 'waiting'
}

function groupConfigs(configs: SystemConfig[]): AiConfigGroup[] {
  const aiKeys = configs.filter((item) => {
    const key = item.key.toLowerCase()
    return key.includes('ai') || key.includes('track') || key.includes('camera')
  })

  return [
    {
      title: 'AI / 自动跟踪参数',
      description: '当前项目没有独立的 AI 配置接口，后台直接复用通用配置中心中的相关配置项。',
      configs: aiKeys,
    },
  ]
}

export function AdminVideoAiPage({
  videoSources,
  configs,
  loading,
  search,
  onSearchChange,
  onRefresh,
  onCreateSource,
  onEditSource,
  onDeleteSource,
  onSaveConfig,
}: {
  videoSources: VideoSource[]
  configs: SystemConfig[]
  loading: boolean
  search: string
  onSearchChange: (value: string) => void
  onRefresh: () => void
  onCreateSource: () => void
  onEditSource: (source: VideoSource) => void
  onDeleteSource: (source: VideoSource) => void
  onSaveConfig: (key: string, value: string | boolean) => Promise<void>
}) {
  useAuthState()
  const canAdmin = hasAuthSession() && hasRole('admin')
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const filteredSources = useMemo(
    () => videoSources.filter((item) => `${item.name} ${item.label}`.toLowerCase().includes(search.toLowerCase())),
    [videoSources, search],
  )

  const aiGroups = useMemo(() => groupConfigs(configs), [configs])

  return (
    <div className="space-y-6">
      <AdminCard
        title="视频源管理"
        subtitle="复用现有 /api/v1/video-sources CRUD，不改当前操作台用的视频链路。"
        actions={
          <div className="flex items-center gap-3">
            <div className="w-72">
              <SearchInput value={search} onChange={onSearchChange} placeholder="搜索摄像头名称 / 标签" />
            </div>
            <ToolbarButton onClick={onRefresh}><RefreshCw size={14} className="inline-block" /> 刷新</ToolbarButton>
            <ToolbarButton onClick={onCreateSource} disabled={!canAdmin} title={!canAdmin ? '需要 admin 权限' : undefined}>新增视频源</ToolbarButton>
          </div>
        }
      >
        {filteredSources.length === 0 ? (
          <EmptyState title="暂无视频源" description="当前数据库里没有视频源，或搜索条件没有匹配结果。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr>
                  <TableHead>名称</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>RTSP</TableHead>
                  <TableHead>WHEP</TableHead>
                  <TableHead>主摄 / AI 源</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>操作</TableHead>
                </tr>
              </thead>
              <tbody>
                {filteredSources.map((source) => (
                  <tr key={source.source_id}>
                    <TableCell>
                      <div className="font-black text-white">{source.label}</div>
                      <div className="mt-1 text-xs text-zinc-500">{source.name}</div>
                    </TableCell>
                    <TableCell>{source.source_type}</TableCell>
                    <TableCell className="max-w-[240px] break-all text-xs text-zinc-300">{source.rtsp_url || '--'}</TableCell>
                    <TableCell className="max-w-[240px] break-all text-xs text-zinc-300">{source.whep_url || '--'}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        {source.is_primary ? <StatusBadge status="normal" /> : null}
                        {source.is_ai_source ? <span className="rounded-full border border-sky-500/30 bg-sky-500/10 px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em] text-sky-300">AI 源</span> : null}
                        {!source.is_primary && !source.is_ai_source ? <span className="text-xs text-zinc-500">普通源</span> : null}
                      </div>
                    </TableCell>
                    <TableCell><StatusBadge status={inferSourceStatus(source) as any} /></TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-2">
                        <ToolbarButton onClick={() => onEditSource(source)} disabled={!canAdmin} title={!canAdmin ? '需要 admin 权限' : undefined}>编辑</ToolbarButton>
                        <ToolbarButton danger onClick={() => onDeleteSource(source)} disabled={!canAdmin} title={!canAdmin ? '需要 admin 权限' : undefined}>删除</ToolbarButton>
                      </div>
                    </TableCell>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AdminCard>

      <div className="grid gap-6 xl:grid-cols-[1fr_0.95fr]">
        <AdminCard title="AI 参数配置" subtitle="这里只展示可复用的配置项。标记“需重启”的参数依然由后端配置定义决定。">
          <div className="space-y-6">
            {aiGroups.map((group) => (
              <div key={group.title} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                <div className="text-sm font-black text-white">{group.title}</div>
                <div className="mt-2 text-sm text-zinc-500">{group.description}</div>
                <div className="mt-4 space-y-3">
                  {group.configs.length === 0 ? (
                    <div className="text-sm text-zinc-500">当前没有匹配到 AI / 摄像头相关配置项。</div>
                  ) : group.configs.map((config) => (
                    <div key={config.key} className="rounded-xl border border-white/8 bg-black/60 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="text-sm font-black text-white">{config.key}</div>
                          <div className="mt-1 text-xs text-zinc-500">{config.description}</div>
                        </div>
                        <span className={`rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.18em] ${config.is_hot_reloadable ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-amber-500/30 bg-amber-500/10 text-amber-300'}`}>
                          {config.is_hot_reloadable ? '热更新' : '需重启'}
                        </span>
                      </div>
                      <div className="mt-4 flex flex-col gap-3 md:flex-row">
                        {config.value_type === 'bool' ? (
                          <select
                            value={String(drafts[config.key] ?? config.value)}
                            onChange={(event) => setDrafts((prev) => ({ ...prev, [config.key]: event.target.value }))}
                            className="rounded-xl border border-white/10 bg-black/60 px-4 py-2.5 text-sm text-white outline-none focus:border-white/30"
                          >
                            <option value="true">true</option>
                            <option value="false">false</option>
                          </select>
                        ) : (
                          <input
                            value={drafts[config.key] ?? String(config.value)}
                            onChange={(event) => setDrafts((prev) => ({ ...prev, [config.key]: event.target.value }))}
                            className="flex-1 rounded-xl border border-white/10 bg-black/60 px-4 py-2.5 text-sm text-white outline-none focus:border-white/30"
                          />
                        )}
                        <ToolbarButton
                          disabled={loading || !canAdmin}
                          title={!canAdmin ? '需要 admin 权限' : undefined}
                          onClick={() => onSaveConfig(config.key, config.value_type === 'bool'
                            ? String(drafts[config.key] ?? config.value) === 'true'
                            : String(drafts[config.key] ?? config.value))}
                        >
                          <Save size={14} className="inline-block" /> 保存
                        </ToolbarButton>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </AdminCard>

        <AdminCard title="运行状态说明" subtitle="偏工程调参与运行状态管理，而不是算法研究面板。">
          <div className="space-y-4">
            <StateNotice title="AI Worker 实时指标" description="当前后台已复用 /ws/event 中的 AI_STATUS 与 AUTO_TRACK_STATUS；更细粒度 FPS、推理耗时、丢帧数还没有独立接口。" />
            <StateNotice title="视频预览" description="当前项目已有操作台实时视频页，本后台先聚焦配置与状态管理，不重复实现一套完整视频舞台。" />
            <StateNotice title="主摄 / 辅摄" description="可直接通过视频源的 is_primary / is_ai_source 维护主画面和 AI 输入源。" />
            <StateNotice title="重启生效提示" description="配置项是否需要重启，完全沿用后端 config 的 is_hot_reloadable 字段，不在前端私自猜测。" />
          </div>
        </AdminCard>
      </div>
    </div>
  )
}

function StateNotice({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
      <div className="flex items-center gap-3">
        <Camera size={16} className="text-zinc-400" />
        <div className="text-sm font-black text-white">{title}</div>
      </div>
      <div className="mt-3 text-sm text-zinc-400">{description}</div>
    </div>
  )
}
