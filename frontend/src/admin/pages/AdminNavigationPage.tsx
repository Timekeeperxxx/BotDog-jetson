import { useMemo, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import type { NavWaypoint, PcdSceneItem, PcdSceneMetadata } from '../../types/pcdMap'
import type { TaskDefinition } from '../../types/taskWorkflow'
import type { SortableNavigationTab } from '../adminTypes'
import { AdminCard, EmptyState, SearchInput, StatusBadge, TableCell, TableHead, ToolbarButton } from '../AdminUi'

function summarizeSteps(task: TaskDefinition) {
  return task.steps.map((step) => {
    if (step.type === 'select_map') return `切换场景 ${step.sceneId || step.mapId}`
    if (step.type === 'relocalize') return `重定位 ${step.mode}`
    return step.x != null && step.y != null && step.z != null && step.yaw != null
      ? `导航至 ${step.waypointName} (${step.x.toFixed(2)}, ${step.y.toFixed(2)}, ${step.z.toFixed(2)}, ${step.yaw.toFixed(3)})`
      : `导航至 ${step.waypointName}`
  })
}

export function AdminNavigationPage({
  scenes,
  selectedSceneId,
  metadata,
  waypoints,
  tasks,
  loading,
  search,
  onSearchChange,
  onRefresh,
  onSelectScene,
  onDeleteWaypoint,
  canOperate = true,
}: {
  scenes: PcdSceneItem[]
  selectedSceneId: string | null
  metadata: PcdSceneMetadata | null
  waypoints: NavWaypoint[]
  tasks: TaskDefinition[]
  loading: boolean
  search: string
  onSearchChange: (value: string) => void
  onRefresh: () => void
  onSelectScene: (sceneId: string) => void
  onDeleteWaypoint: (waypoint: NavWaypoint) => void
  canOperate?: boolean
}) {
  const [tab, setTab] = useState<SortableNavigationTab>('maps')

  const filteredScenes = useMemo(
    () => scenes.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())),
    [scenes, search],
  )

  const filteredWaypoints = useMemo(
    () => waypoints.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())),
    [waypoints, search],
  )

  const filteredTasks = useMemo(
    () => tasks.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())),
    [tasks, search],
  )

  return (
    <div className="space-y-6">
      <AdminCard
        title="导航资源管理"
        subtitle={loading ? '导航资源加载中…' : '场景、点位和巡逻任务是后台核心资源。'}
        actions={
          <div className="flex items-center gap-3">
            <div className="w-72">
              <SearchInput value={search} onChange={onSearchChange} placeholder="搜索场景 / 点位 / 任务名称" />
            </div>
            <ToolbarButton onClick={onRefresh}><RefreshCw size={14} className="inline-block" /> 刷新</ToolbarButton>
          </div>
        }
      >
        <div className="flex flex-wrap gap-3">
          <NavTabButton active={tab === 'maps'} label="场景管理" onClick={() => setTab('maps')} />
          <NavTabButton active={tab === 'waypoints'} label="点位管理" onClick={() => setTab('waypoints')} />
          <NavTabButton active={tab === 'tasks'} label="巡逻任务" onClick={() => setTab('tasks')} />
        </div>
      </AdminCard>

      {tab === 'maps' ? (
        <div className="grid gap-6 xl:grid-cols-[1fr_0.9fr]">
          <AdminCard title="场景列表" subtitle="当前优先复用 /api/v1/nav/pcd-scenes。">
            {filteredScenes.length === 0 ? (
              <EmptyState title="暂无场景" description="当前场景根目录没有可用文件夹，或搜索条件没有匹配结果。" />
            ) : (
              <div className="space-y-3">
                {filteredScenes.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => onSelectScene(item.id)}
                    className={`w-full rounded-2xl border p-4 text-left transition-all ${
                      selectedSceneId === item.id
                        ? 'border-white/30 bg-white/8'
                        : 'border-white/8 bg-black/40 hover:border-white/16 hover:bg-white/3'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-medium text-white">{item.name}</div>
                        <div className="mt-2 text-xs text-zinc-500">{item.id}</div>
                      </div>
                      <StatusBadge status={selectedSceneId === item.id ? 'normal' : 'waiting'} />
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      <InfoChip label="场景状态" value={item.ready ? 'ready' : 'incomplete'} />
                      <InfoChip label="更新时间" value={new Date(item.modified_at).toLocaleString('zh-CN', { hour12: false })} />
                      <InfoChip label="可导航" value={item.navigable ? 'yes' : 'no'} />
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <ToolbarButton disabled>重命名</ToolbarButton>
                      <ToolbarButton disabled>设为当前</ToolbarButton>
                      <ToolbarButton disabled danger>删除</ToolbarButton>
                    </div>
                  </button>
                ))}
              </div>
          )}
          </AdminCard>

          <AdminCard title="场景详情" subtitle="预览优先展示 metadata 和点位数量；真正点云预览仍在操作台导航页。">
            {!selectedSceneId ? (
              <EmptyState title="未选择场景" description="从左侧场景列表中选择一个 SceneN_ 文件夹后，这里会显示元数据、边界和点位概览。" />
            ) : (
              <div className="space-y-4">
                <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
                  <div className="text-sm font-medium text-white">{selectedSceneId}</div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <InfoChip label="frame_id" value={metadata?.frame_id || 'map'} />
                    <InfoChip label="点数量" value={metadata?.point_count?.toLocaleString?.() || '--'} />
                    <InfoChip label="字段" value={metadata?.fields?.join(', ') || '--'} />
                    <InfoChip label="数据类型" value={metadata?.data_type || '--'} />
                  </div>
                </div>
                <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
                  <div className="text-sm font-medium text-white">边界信息</div>
                  {metadata?.bounds ? (
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <InfoChip label="X" value={`${metadata.bounds.min_x.toFixed(2)} ~ ${metadata.bounds.max_x.toFixed(2)}`} />
                      <InfoChip label="Y" value={`${metadata.bounds.min_y.toFixed(2)} ~ ${metadata.bounds.max_y.toFixed(2)}`} />
                      <InfoChip label="Z" value={`${metadata.bounds.min_z.toFixed(2)} ~ ${metadata.bounds.max_z.toFixed(2)}`} />
                      <InfoChip label="点位数" value={`${waypoints.length}`} />
                    </div>
                  ) : (
                    <div className="mt-3 text-sm text-zinc-500">当前场景还没有可用边界信息。</div>
                  )}
                </div>
              </div>
            )}
          </AdminCard>
        </div>
      ) : null}

      {tab === 'waypoints' ? (
        <AdminCard title="点位管理" subtitle="复用 /api/v1/nav/pcd-maps/{scene_id}/waypoints。当前后端仅支持新增、删除和单点导航，不支持编辑。">
          {!selectedSceneId ? (
            <EmptyState title="未选择场景" description="点位是场景下资源，请先在场景列表中选择一个 SceneN_ 文件夹。" />
          ) : filteredWaypoints.length === 0 ? (
            <EmptyState title="暂无点位" description="这张场景还没有导航点，或搜索条件没有匹配结果。" />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr>
                    <TableHead>点位名称</TableHead>
                    <TableHead>所属场景</TableHead>
                    <TableHead>X / Y / Z</TableHead>
                    <TableHead>Yaw</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>操作</TableHead>
                  </tr>
                </thead>
                <tbody>
                  {filteredWaypoints.map((item) => (
                    <tr key={item.id}>
                      <TableCell>{item.name}</TableCell>
                      <TableCell className="font-mono text-xs">{item.map_id}</TableCell>
                      <TableCell className="font-mono text-xs">{item.x.toFixed(2)} / {item.y.toFixed(2)} / {item.z.toFixed(2)}</TableCell>
                      <TableCell className="font-mono text-xs">{item.yaw.toFixed(3)}</TableCell>
                      <TableCell><StatusBadge status="normal" /></TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          <ToolbarButton disabled>编辑</ToolbarButton>
                          <ToolbarButton
                            danger
                            onClick={() => onDeleteWaypoint(item)}
                            disabled={!canOperate}
                            title={!canOperate ? '需要 operator 权限' : undefined}
                          >
                            <Trash2 size={14} className="inline-block" /> 删除
                          </ToolbarButton>
                        </div>
                      </TableCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </AdminCard>
      ) : null}

      {tab === 'tasks' ? (
        <AdminCard title="巡逻任务" subtitle="当前任务定义由后端统一保存在 data 目录下的 JSON 文件中。">
          {filteredTasks.length === 0 ? (
            <EmptyState title="暂无巡逻任务" description="当前 JSON 任务文件里没有任务定义。" />
          ) : (
            <div className="space-y-3">
              {filteredTasks.map((task) => (
                <div key={task.id} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-white">{task.name}</div>
                      <div className="mt-2 text-xs text-zinc-500">场景={task.sceneId || task.mapId || task.mapName} · 创建时间={new Date(task.createdAt).toLocaleString('zh-CN', { hour12: false })}</div>
                    </div>
                    <StatusBadge status="todo" />
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <InfoChip label="任务类型" value="巡逻导航" />
                    <InfoChip label="循环模式" value="当前版本未接入" />
                    <InfoChip label="失败策略" value="当前版本未接入" />
                  </div>
                  <div className="mt-4">
                    <div className="text-xs font-medium text-zinc-500">步骤</div>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {summarizeSteps(task).map((step, index) => (
                        <span key={`${task.id}-${index}`} className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-zinc-300">
                          {step}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </AdminCard>
      ) : null}

      {tab === 'history' ? (
        <AdminCard title="任务历史" subtitle="当前版本未接入任务历史查询。">
          <EmptyState title="任务历史暂未启用" description="后续如果接入任务执行记录表，这里再补充筛选和统计能力。" />
        </AdminCard>
      ) : null}
    </div>
  )
}

function NavTabButton({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-4 py-2 text-sm font-medium transition-all ${
        active ? 'border-white/30 bg-white/10 text-white' : 'border-white/10 text-zinc-500 hover:border-white/20 hover:text-white'
      }`}
    >
      {label}
    </button>
  )
}

function InfoChip({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="rounded-xl border border-white/8 bg-black/50 p-3">
      <div className="text-xs font-medium text-zinc-500">{label}</div>
      <div className="mt-2 text-sm text-zinc-200">{value}</div>
    </div>
  )
}
