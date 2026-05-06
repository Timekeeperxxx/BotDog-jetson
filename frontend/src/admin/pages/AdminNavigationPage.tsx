import { useMemo, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import type { NavWaypoint, PcdMapItem, PcdMetadata } from '../../types/pcdMap'
import type { TaskDefinition } from '../../types/taskWorkflow'
import type { SortableNavigationTab } from '../adminTypes'
import { AdminCard, EmptyState, SearchInput, StatusBadge, TableCell, TableHead, ToolbarButton } from '../AdminUi'

function summarizeSteps(task: TaskDefinition) {
  return task.steps.map((step) => {
    if (step.type === 'select_map') return `切换地图 ${step.mapId}`
    if (step.type === 'relocalize') return `重定位 ${step.mode}`
    return `导航至 ${step.waypointName}`
  })
}

function formatMapSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

export function AdminNavigationPage({
  maps,
  selectedMapId,
  metadata,
  waypoints,
  tasks,
  loading,
  search,
  onSearchChange,
  onRefresh,
  onSelectMap,
  onDeleteWaypoint,
}: {
  maps: PcdMapItem[]
  selectedMapId: string | null
  metadata: PcdMetadata | null
  waypoints: NavWaypoint[]
  tasks: TaskDefinition[]
  loading: boolean
  search: string
  onSearchChange: (value: string) => void
  onRefresh: () => void
  onSelectMap: (mapId: string) => void
  onDeleteWaypoint: (waypoint: NavWaypoint) => void
}) {
  const [tab, setTab] = useState<SortableNavigationTab>('maps')

  const filteredMaps = useMemo(
    () => maps.filter((item) => item.name.toLowerCase().includes(search.toLowerCase())),
    [maps, search],
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
        subtitle={loading ? '导航资源加载中…' : '地图、点位和巡逻任务属于后台核心资源；任务历史目前缺少后端接口，只做明确占位。'}
        actions={
          <div className="flex items-center gap-3">
            <div className="w-72">
              <SearchInput value={search} onChange={onSearchChange} placeholder="搜索地图 / 点位 / 任务名称" />
            </div>
            <ToolbarButton onClick={onRefresh}><RefreshCw size={14} className="inline-block" /> 刷新</ToolbarButton>
          </div>
        }
      >
        <div className="flex flex-wrap gap-3">
          <NavTabButton active={tab === 'maps'} label="地图管理" onClick={() => setTab('maps')} />
          <NavTabButton active={tab === 'waypoints'} label="点位管理" onClick={() => setTab('waypoints')} />
          <NavTabButton active={tab === 'tasks'} label="巡逻任务" onClick={() => setTab('tasks')} />
          <NavTabButton active={tab === 'history'} label="任务历史" onClick={() => setTab('history')} />
        </div>
      </AdminCard>

      {tab === 'maps' ? (
        <div className="grid gap-6 xl:grid-cols-[1fr_0.9fr]">
          <AdminCard title="PCD 地图列表" subtitle="当前直接复用 /api/v1/nav/pcd-maps。">
            {filteredMaps.length === 0 ? (
              <EmptyState title="暂无地图" description="当前 PCD 根目录没有地图文件，或搜索条件没有匹配结果。" />
            ) : (
              <div className="space-y-3">
                {filteredMaps.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => onSelectMap(item.id)}
                    className={`w-full rounded-2xl border p-4 text-left transition-all ${
                      selectedMapId === item.id
                        ? 'border-white/30 bg-white/8'
                        : 'border-white/8 bg-black/40 hover:border-white/16 hover:bg-white/3'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-black text-white">{item.name}</div>
                        <div className="mt-2 text-xs text-zinc-500">{item.id}</div>
                      </div>
                      <StatusBadge status={selectedMapId === item.id ? 'normal' : 'waiting'} />
                    </div>
                    <div className="mt-4 grid gap-3 md:grid-cols-3">
                      <InfoChip label="文件大小" value={formatMapSize(item.size_bytes)} />
                      <InfoChip label="更新时间" value={new Date(item.modified_at).toLocaleString('zh-CN', { hour12: false })} />
                      <InfoChip label="默认地图" value="TODO：后端暂无默认地图接口" />
                    </div>
                    <div className="mt-4 flex flex-wrap gap-2">
                      <ToolbarButton disabled>重命名</ToolbarButton>
                      <ToolbarButton disabled>设为默认</ToolbarButton>
                      <ToolbarButton disabled danger>删除</ToolbarButton>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </AdminCard>

          <AdminCard title="地图详情" subtitle="预览优先展示 metadata 和点位数量；真正点云预览仍在操作台导航页。">
            {!selectedMapId ? (
              <EmptyState title="未选择地图" description="从左侧地图列表中选择一张 PCD 地图后，这里会显示元数据、边界和点位概览。" />
            ) : (
              <div className="space-y-4">
                <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
                  <div className="text-sm font-black text-white">{selectedMapId}</div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <InfoChip label="frame_id" value={metadata?.frame_id || 'map'} />
                    <InfoChip label="点数量" value={metadata?.point_count?.toLocaleString?.() || '--'} />
                    <InfoChip label="字段" value={metadata?.fields?.join(', ') || '--'} />
                    <InfoChip label="数据类型" value={metadata?.data_type || '--'} />
                  </div>
                </div>
                <div className="rounded-2xl border border-white/8 bg-black/40 p-4">
                  <div className="text-sm font-black text-white">边界信息</div>
                  {metadata?.bounds ? (
                    <div className="mt-4 grid gap-3 md:grid-cols-2">
                      <InfoChip label="X" value={`${metadata.bounds.min_x.toFixed(2)} ~ ${metadata.bounds.max_x.toFixed(2)}`} />
                      <InfoChip label="Y" value={`${metadata.bounds.min_y.toFixed(2)} ~ ${metadata.bounds.max_y.toFixed(2)}`} />
                      <InfoChip label="Z" value={`${metadata.bounds.min_z.toFixed(2)} ~ ${metadata.bounds.max_z.toFixed(2)}`} />
                      <InfoChip label="点位数" value={`${waypoints.length}`} />
                    </div>
                  ) : (
                    <div className="mt-3 text-sm text-zinc-500">当前地图还没有可用边界信息。</div>
                  )}
                </div>
              </div>
            )}
          </AdminCard>
        </div>
      ) : null}

      {tab === 'waypoints' ? (
        <AdminCard title="点位管理" subtitle="复用 /api/v1/nav/pcd-maps/{map_id}/waypoints。当前后端仅支持新增、删除和单点导航，不支持编辑。">
          {!selectedMapId ? (
            <EmptyState title="未选择地图" description="点位是地图下资源，请先在地图管理页选择一张 PCD 地图。" />
          ) : filteredWaypoints.length === 0 ? (
            <EmptyState title="暂无点位" description="这张地图还没有导航点，或搜索条件没有匹配结果。" />
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr>
                    <TableHead>点位名称</TableHead>
                    <TableHead>所属地图</TableHead>
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
                          <ToolbarButton danger onClick={() => onDeleteWaypoint(item)}>
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
        <AdminCard title="巡逻任务" subtitle="当前项目没有后端任务资源 CRUD；这里展示的是操作台保存在 localStorage 的任务定义，并明确标记来源。">
          {filteredTasks.length === 0 ? (
            <EmptyState title="暂无巡逻任务" description="当前没有保存到 localStorage 的任务定义。要真正做后台级任务管理，需要新增后端任务资源接口。" />
          ) : (
            <div className="space-y-3">
              {filteredTasks.map((task) => (
                <div key={task.id} className="rounded-2xl border border-white/8 bg-black/40 p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-black text-white">{task.name}</div>
                      <div className="mt-2 text-xs text-zinc-500">地图={task.mapName} · 创建时间={new Date(task.createdAt).toLocaleString('zh-CN', { hour12: false })}</div>
                    </div>
                    <StatusBadge status="todo" />
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <InfoChip label="任务类型" value="巡逻导航" />
                    <InfoChip label="循环模式" value="TODO：当前结构未记录" />
                    <InfoChip label="失败策略" value="TODO：当前结构未记录" />
                  </div>
                  <div className="mt-4">
                    <div className="text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">步骤</div>
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
        <AdminCard title="任务历史" subtitle="当前项目没有任务历史查询接口，因此这里只展示明确占位，不伪造运行记录。">
          <EmptyState title="任务历史待接入" description="建议后续新增任务执行记录表和 /api/v1/nav/tasks/history 接口，再在后台管理里做筛选、耗时统计和失败原因追踪。" />
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
      className={`rounded-full border px-4 py-2 text-[11px] font-black uppercase tracking-[0.18em] transition-all ${
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
      <div className="text-[10px] font-black uppercase tracking-[0.18em] text-zinc-500">{label}</div>
      <div className="mt-2 text-sm text-zinc-200">{value}</div>
    </div>
  )
}
