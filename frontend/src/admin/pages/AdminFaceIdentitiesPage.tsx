import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, ScanFace, Upload } from 'lucide-react'
import { faceIdentitiesApi, type FaceIdentity, type FaceRecognitionStatus } from '../../api/faceIdentitiesApi'
import { AdminCard, ConfirmDialog, EmptyState, StatusBadge, TableCell, TableHead, ToolbarButton } from '../AdminUi'

export function AdminFaceIdentitiesPage() {
  const [identities, setIdentities] = useState<FaceIdentity[]>([])
  const [recognitionStatus, setRecognitionStatus] = useState<FaceRecognitionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<FaceIdentity | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [notes, setNotes] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [saving, setSaving] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<FaceIdentity | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [items, status] = await Promise.all([
        faceIdentitiesApi.list(),
        faceIdentitiesApi.status(),
      ])
      setIdentities(items)
      setRecognitionStatus(status)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '人员库加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const openCreate = () => {
    setEditing(null)
    setDisplayName('')
    setNotes('')
    setEnabled(true)
    setFormOpen(true)
  }

  const openEdit = (identity: FaceIdentity) => {
    setEditing(identity)
    setDisplayName(identity.display_name)
    setNotes(identity.notes ?? '')
    setEnabled(identity.enabled)
    setFormOpen(true)
  }

  const save = async () => {
    const name = displayName.trim()
    if (!name) {
      setError('姓名不能为空')
      return
    }
    setSaving(true)
    setError(null)
    try {
      if (editing) {
        await faceIdentitiesApi.update(editing.id, {
          display_name: name,
          notes: notes.trim() || null,
          enabled,
        })
      } else {
        await faceIdentitiesApi.create({
          display_name: name,
          notes: notes.trim() || null,
          enabled,
        })
      }
      setFormOpen(false)
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const uploadTemplate = async (identity: FaceIdentity, file?: File) => {
    if (!file) return
    setSaving(true)
    setError(null)
    try {
      await faceIdentitiesApi.addTemplate(identity.id, file)
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '人脸图片注册失败')
    } finally {
      setSaving(false)
    }
  }

  const deleteTemplate = async (identityId: number, templateId: number) => {
    setSaving(true)
    setError(null)
    try {
      await faceIdentitiesApi.deleteTemplate(identityId, templateId)
      await refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '删除模板失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      <AdminCard
        title="人脸识别状态"
        subtitle="YuNet 检测 + SFace 特征匹配。识别只用于显示姓名，不触发开锁或机器人动作。"
        actions={<ToolbarButton onClick={() => void refresh()} disabled={loading}><RefreshCw size={14} className="inline-block" /> 刷新</ToolbarButton>}
      >
        <div className="grid gap-4 md:grid-cols-4">
          <StatusItem label="服务状态" value={recognitionStatus?.available ? '可用' : '不可用'} status={recognitionStatus?.available ? 'normal' : 'degraded'} />
          <StatusItem label="已启用人员" value={String(recognitionStatus?.identity_count ?? 0)} status="normal" />
          <StatusItem label="特征模板" value={String(recognitionStatus?.template_count ?? 0)} status="normal" />
          <StatusItem label="匹配阈值" value={recognitionStatus?.match_threshold.toFixed(2) ?? '--'} status="normal" />
        </div>
        {recognitionStatus?.error ? <div className="mt-4 rounded-md border border-amber-500/20 bg-amber-500/10 p-3 text-sm text-amber-300">{recognitionStatus.error}</div> : null}
      </AdminCard>

      <AdminCard
        title="人员库"
        subtitle="每个人员最多 5 个模板；注册图片必须且只能有一张清晰正脸，原图不会保存。"
        actions={<ToolbarButton onClick={openCreate}><ScanFace size={14} className="inline-block" /> 新增人员</ToolbarButton>}
      >
        {error ? <div className="mb-4 rounded-md border border-red-500/20 bg-red-500/10 p-3 text-sm text-red-300">{error}</div> : null}
        {!loading && identities.length === 0 ? (
          <EmptyState title="暂无人员" description="先新增人员，再上传一到五张清晰正脸照片。" />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead><tr><TableHead>姓名</TableHead><TableHead>状态</TableHead><TableHead>人脸模板</TableHead><TableHead>备注</TableHead><TableHead>操作</TableHead></tr></thead>
              <tbody>
                {identities.map((identity) => (
                  <tr key={identity.id}>
                    <TableCell><div className="font-semibold text-white">{identity.display_name}</div><div className="mt-1 text-xs text-zinc-500">#{identity.id}</div></TableCell>
                    <TableCell><StatusBadge status={identity.enabled ? 'normal' : 'degraded'} /></TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-2">
                        {identity.templates.map((template) => (
                          <button key={template.id} type="button" disabled={saving} onClick={() => void deleteTemplate(identity.id, template.id)} className="rounded border border-white/10 px-2 py-1 text-xs text-zinc-300 hover:border-red-500/50 hover:text-red-300" title="点击删除此模板">
                            模板 #{template.id} · 质量 {Math.round(template.quality * 100)}%
                          </button>
                        ))}
                        <label className="cursor-pointer rounded border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-xs text-sky-300 hover:bg-sky-500/20">
                          <Upload size={12} className="mr-1 inline-block" /> 上传正脸
                          <input type="file" accept="image/jpeg,image/png,image/webp" className="hidden" disabled={saving || identity.templates.length >= 5} onChange={(event) => { void uploadTemplate(identity, event.target.files?.[0]); event.currentTarget.value = '' }} />
                        </label>
                      </div>
                    </TableCell>
                    <TableCell className="max-w-72 text-zinc-400">{identity.notes || '--'}</TableCell>
                    <TableCell><div className="flex gap-2"><ToolbarButton onClick={() => openEdit(identity)}>编辑</ToolbarButton><ToolbarButton danger onClick={() => setDeleteTarget(identity)}>删除</ToolbarButton></div></TableCell>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </AdminCard>

      {formOpen ? (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/75 px-4">
          <div role="dialog" aria-modal="true" className="w-full max-w-md rounded-lg border border-white/12 bg-[#15191e] p-5 shadow-xl">
            <h3 className="text-lg font-semibold text-white">{editing ? '编辑人员' : '新增人员'}</h3>
            <div className="mt-5 space-y-4">
              <label className="block text-sm text-zinc-300">显示姓名<input autoFocus value={displayName} onChange={(event) => setDisplayName(event.target.value)} maxLength={100} className="mt-2 w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-white outline-none focus:border-sky-600" /></label>
              <label className="block text-sm text-zinc-300">备注<textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={500} rows={3} className="mt-2 w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-white outline-none focus:border-sky-600" /></label>
              <label className="flex items-center gap-2 text-sm text-zinc-300"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} /> 启用识别</label>
            </div>
            <div className="mt-6 flex justify-end gap-3"><ToolbarButton onClick={() => setFormOpen(false)} disabled={saving}>取消</ToolbarButton><ToolbarButton onClick={() => void save()} disabled={saving}>{saving ? '保存中' : '保存'}</ToolbarButton></div>
          </div>
        </div>
      ) : null}

      <ConfirmDialog open={deleteTarget !== null} title="删除人员" description={`将永久删除“${deleteTarget?.display_name ?? ''}”及其全部人脸模板，立即停止匹配。`} confirmText="永久删除" danger disabled={saving} onCancel={() => setDeleteTarget(null)} onConfirm={() => { if (!deleteTarget) return; setSaving(true); void faceIdentitiesApi.delete(deleteTarget.id).then(refresh).catch((reason) => setError(reason instanceof Error ? reason.message : '删除失败')).finally(() => { setSaving(false); setDeleteTarget(null) }) }} />
    </div>
  )
}

function StatusItem({ label, value, status }: { label: string; value: string; status: 'normal' | 'degraded' }) {
  return <div className="rounded-md border border-white/8 bg-black/30 p-4"><div className="text-xs text-zinc-500">{label}</div><div className="mt-2 flex items-center justify-between"><span className="text-lg font-semibold text-white">{value}</span><StatusBadge status={status} /></div></div>
}
