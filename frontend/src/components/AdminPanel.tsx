/**
 * BOTDOG // 后台管理面板
 * 视频源 & 网口配置管理 - 工业终端风格
 */

import { useState, useEffect } from 'react';
import { useVideoSources } from '../hooks/useVideoSources';
import type { VideoSource, VideoSourceRequest, NetworkInterface, NetworkInterfaceRequest } from '../types/admin';
import { getApiUrl } from '../config/api';
import {
  RefreshCw, Plus, Trash2, Edit3, CheckCircle2, AlertTriangle, X,
  Video, Wifi, Save, Camera, Network, Star, Cpu, Info, Lock,
} from 'lucide-react';

interface AdminPanelProps {
  onClose?: () => void;
}

type AdminTab = 'video' | 'network' | 'sysinfo';

interface SysInfoItem {
  key: string;
  label: string;
  value: string;
  note: string;
  env_key: string;
}

interface SysInfoGroup {
  group: string;
  icon: string;
  items: SysInfoItem[];
}

// ── 编辑表单（视频源）──────────────────────────────────────────
interface VideoFormData {
  name: string;
  label: string;
  source_type: string;
  whep_url: string;
  rtsp_url: string;
  enabled: boolean;
  is_primary: boolean;
  is_ai_source: boolean;
  sort_order: number;
}

function emptyVideoForm(): VideoFormData {
  return {
    name: '', label: '', source_type: 'whep',
    whep_url: '', rtsp_url: '',
    enabled: true, is_primary: false, is_ai_source: false, sort_order: 0,
  };
}

function sourceToForm(src: VideoSource): VideoFormData {
  return {
    name: src.name, label: src.label, source_type: src.source_type,
    whep_url: src.whep_url || '', rtsp_url: src.rtsp_url || '',
    enabled: src.enabled, is_primary: src.is_primary, is_ai_source: src.is_ai_source,
    sort_order: src.sort_order,
  };
}

// ── 编辑表单（网口）────────────────────────────────────────────
interface IfaceFormData {
  name: string;
  label: string;
  iface_name: string;
  ip_address: string;
  purpose: string;
  enabled: boolean;
}

function emptyIfaceForm(): IfaceFormData {
  return { name: '', label: '', iface_name: '', ip_address: '', purpose: 'other', enabled: true };
}

function ifaceToForm(iface: NetworkInterface): IfaceFormData {
  return {
    name: iface.name, label: iface.label, iface_name: iface.iface_name,
    ip_address: iface.ip_address || '', purpose: iface.purpose, enabled: iface.enabled,
  };
}

// ── 通用输入行组件 ──────────────────────────────────────────────
function FormRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[9px] font-bold uppercase tracking-[0.2em] text-zinc-400">{label}</label>
      {children}
    </div>
  );
}

function TextInput({ value, onChange, placeholder, disabled }: {
  value: string; onChange: (v: string) => void; placeholder?: string; disabled?: boolean;
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="bg-zinc-950 border border-zinc-700 px-3 py-2 text-xs text-white font-mono
        focus:outline-none focus:border-white transition-all placeholder-zinc-600
        disabled:opacity-40 disabled:cursor-not-allowed w-full"
    />
  );
}

function Toggle({ checked, onChange, label, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean;
}) {
  return (
    <label className="flex items-center gap-3 cursor-pointer select-none">
      <div className="relative" onClick={() => !disabled && onChange(!checked)}>
        <div className={`w-9 h-[18px] border transition-all ${
          checked ? 'bg-white border-white' : 'bg-zinc-900 border-zinc-600'
        }`} />
        <div className={`absolute top-[1px] w-4 h-4 transition-transform duration-200 ${
          checked ? 'translate-x-[18px] bg-black' : 'translate-x-[1px] bg-zinc-500'
        }`} />
      </div>
      <span className={`text-[10px] font-bold uppercase tracking-[0.15em] ${
        checked ? 'text-white' : 'text-zinc-500'
      }`}>{label}</span>
    </label>
  );
}

// ==================== 主面板 ====================
export function AdminPanel({ onClose }: AdminPanelProps) {
  const admin = useVideoSources();
  const [activeTab, setActiveTab] = useState<AdminTab>('video');
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [sysInfo, setSysInfo] = useState<SysInfoGroup[]>([]);
  const [sysInfoLoading, setSysInfoLoading] = useState(false);

  // 视频源编辑状态
  const [editingSourceId, setEditingSourceId] = useState<number | null>(null); // null=新增, number=编辑
  const [showSourceForm, setShowSourceForm] = useState(false);
  const [sourceForm, setSourceForm] = useState<VideoFormData>(emptyVideoForm());
  const [deletingSourceId, setDeletingSourceId] = useState<number | null>(null);

  // 网口编辑状态
  const [editingIfaceId, setEditingIfaceId] = useState<number | null>(null);
  const [showIfaceForm, setShowIfaceForm] = useState(false);
  const [ifaceForm, setIfaceForm] = useState<IfaceFormData>(emptyIfaceForm());
  const [deletingIfaceId, setDeletingIfaceId] = useState<number | null>(null);

  useEffect(() => {
    admin.fetchSources();
    admin.fetchInterfaces();
    // 拉取系统硬件信息
    setSysInfoLoading(true);
    fetch(getApiUrl('/api/v1/system-info'))
      .then(r => r.json())
      .then(d => setSysInfo(d.groups || []))
      .catch(() => {})
      .finally(() => setSysInfoLoading(false));
  }, []);

  const showSuccess = (msg: string) => {
    setSuccessMsg(msg);
    setTimeout(() => setSuccessMsg(null), 3000);
  };

  // ── 视频源操作 ────────────────────────────────────────────
  const openNewSource = () => {
    setSourceForm(emptyVideoForm());
    setEditingSourceId(null);
    setShowSourceForm(true);
  };

  const openEditSource = (src: VideoSource) => {
    setSourceForm(sourceToForm(src));
    setEditingSourceId(src.source_id);
    setShowSourceForm(true);
  };

  const handleSaveSource = async () => {
    try {
      const req: VideoSourceRequest = {
        name: sourceForm.name,
        label: sourceForm.label,
        source_type: sourceForm.source_type as VideoSourceRequest['source_type'],
        whep_url: sourceForm.whep_url || null,
        rtsp_url: sourceForm.rtsp_url || null,
        enabled: sourceForm.enabled,
        is_primary: sourceForm.is_primary,
        is_ai_source: sourceForm.is_ai_source,
        sort_order: sourceForm.sort_order,
      };
      if (editingSourceId !== null) {
        await admin.updateSource(editingSourceId, req);
        showSuccess(`视频源 [${sourceForm.name}] 更新成功`);
      } else {
        await admin.createSource(req);
        showSuccess(`视频源 [${sourceForm.name}] 创建成功`);
      }
      setShowSourceForm(false);
    } catch {
      // error already in admin.error
    }
  };

  const handleDeleteSource = async (id: number) => {
    try {
      await admin.deleteSource(id);
      setDeletingSourceId(null);
      showSuccess('视频源已删除');
    } catch {
      // error in admin.error
    }
  };

  // ── 网口操作 ────────────────────────────────────────────
  const openNewIface = () => {
    setIfaceForm(emptyIfaceForm());
    setEditingIfaceId(null);
    setShowIfaceForm(true);
  };

  const openEditIface = (iface: NetworkInterface) => {
    setIfaceForm(ifaceToForm(iface));
    setEditingIfaceId(iface.iface_id);
    setShowIfaceForm(true);
  };

  const handleSaveIface = async () => {
    try {
      const req: NetworkInterfaceRequest = {
        name: ifaceForm.name,
        label: ifaceForm.label,
        iface_name: ifaceForm.iface_name,
        ip_address: ifaceForm.ip_address || null,
        purpose: ifaceForm.purpose as NetworkInterfaceRequest['purpose'],
        enabled: ifaceForm.enabled,
      };
      if (editingIfaceId !== null) {
        await admin.updateInterface(editingIfaceId, req);
        showSuccess(`网口 [${ifaceForm.name}] 更新成功`);
      } else {
        await admin.createInterface(req);
        showSuccess(`网口 [${ifaceForm.name}] 创建成功`);
      }
      setShowIfaceForm(false);
    } catch {
      // error in admin.error
    }
  };

  const handleDeleteIface = async (id: number) => {
    try {
      await admin.deleteInterface(id);
      setDeletingIfaceId(null);
      showSuccess('网口配置已删除');
    } catch {
      // error in admin.error
    }
  };

  // ── 渲染：视频源卡片 ──────────────────────────────────────
  const renderSourceCard = (src: VideoSource) => (
    <div key={src.source_id} className="bg-black p-4 group hover:bg-zinc-950 transition-colors relative">
      {/* 删除确认浮层 */}
      {deletingSourceId === src.source_id && (
        <div className="absolute inset-0 bg-black/95 z-10 flex items-center justify-center gap-4 border border-red-500/30">
          <span className="text-[10px] font-bold text-red-400 uppercase tracking-widest">确认删除？</span>
          <button
            onClick={() => handleDeleteSource(src.source_id)}
            className="px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest bg-red-600 text-white hover:bg-red-500 transition-all"
          >删除</button>
          <button
            onClick={() => setDeletingSourceId(null)}
            className="px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest border border-zinc-600 text-zinc-300 hover:text-white hover:border-white transition-all"
          >取消</button>
        </div>
      )}

      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${src.enabled ? 'bg-emerald-500' : 'bg-zinc-600'}`} />
          <span className="text-sm font-bold tracking-widest uppercase text-white font-mono">{src.name}</span>
          <span className="text-[10px] text-zinc-400 font-mono">// {src.label}</span>
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => openEditSource(src)}
            className="p-1.5 text-zinc-500 hover:text-white transition-colors"
            title="编辑"
          >
            <Edit3 size={12} />
          </button>
          <button
            onClick={() => setDeletingSourceId(src.source_id)}
            className="p-1.5 text-zinc-500 hover:text-red-400 transition-colors"
            title="删除"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {/* 地址信息 */}
      <div className="ml-5 space-y-1.5 text-[10px] font-mono">
        {src.whep_url && (
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 w-10 shrink-0">WHEP</span>
            <span className="text-zinc-200 truncate">{src.whep_url}</span>
          </div>
        )}
        {src.rtsp_url && (
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 w-10 shrink-0">RTSP</span>
            <span className="text-zinc-200 truncate">{src.rtsp_url}</span>
          </div>
        )}
        {!src.whep_url && !src.rtsp_url && (
          <div className="text-zinc-600 italic">未配置地址</div>
        )}
      </div>

      {/* 标签行 */}
      <div className="ml-5 flex items-center gap-3 mt-3 flex-wrap">
        <span className={`text-[8px] px-2 py-0.5 border font-bold uppercase tracking-wider ${
          src.enabled
            ? 'border-emerald-500/40 text-emerald-400'
            : 'border-zinc-700 text-zinc-500'
        }`}>
          {src.enabled ? '已启用' : '已禁用'}
        </span>
        {src.is_primary && (
          <span className="text-[8px] px-2 py-0.5 border border-amber-500/40 text-amber-400 font-bold uppercase tracking-wider flex items-center gap-1">
            <Star size={8} /> 主画面
          </span>
        )}
        {src.is_ai_source && (
          <span className="text-[8px] px-2 py-0.5 border border-cyan-500/40 text-cyan-400 font-bold uppercase tracking-wider flex items-center gap-1">
            <Cpu size={8} /> AI 源
          </span>
        )}
        <span className="text-[8px] px-2 py-0.5 border border-zinc-700 text-zinc-500 font-bold uppercase tracking-wider">
          {src.source_type}
        </span>
      </div>
    </div>
  );

  // ── 渲染：网口卡片 ──────────────────────────────────────
  const renderIfaceCard = (iface: NetworkInterface) => (
    <div key={iface.iface_id} className="bg-black p-4 group hover:bg-zinc-950 transition-colors relative">
      {/* 删除确认浮层 */}
      {deletingIfaceId === iface.iface_id && (
        <div className="absolute inset-0 bg-black/95 z-10 flex items-center justify-center gap-4 border border-red-500/30">
          <span className="text-[10px] font-bold text-red-400 uppercase tracking-widest">确认删除？</span>
          <button
            onClick={() => handleDeleteIface(iface.iface_id)}
            className="px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest bg-red-600 text-white hover:bg-red-500 transition-all"
          >删除</button>
          <button
            onClick={() => setDeletingIfaceId(null)}
            className="px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest border border-zinc-600 text-zinc-300 hover:text-white hover:border-white transition-all"
          >取消</button>
        </div>
      )}

      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${iface.enabled ? 'bg-emerald-500' : 'bg-zinc-600'}`} />
          <span className="text-sm font-bold tracking-widest uppercase text-white font-mono">{iface.name}</span>
          <span className="text-[10px] text-zinc-400 font-mono">// {iface.label}</span>
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={() => openEditIface(iface)}
            className="p-1.5 text-zinc-500 hover:text-white transition-colors"
            title="编辑"
          >
            <Edit3 size={12} />
          </button>
          <button
            onClick={() => setDeletingIfaceId(iface.iface_id)}
            className="p-1.5 text-zinc-500 hover:text-red-400 transition-colors"
            title="删除"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      <div className="ml-5 space-y-1.5 text-[10px] font-mono">
        <div className="flex items-center gap-2">
          <span className="text-zinc-500 w-14 shrink-0">网卡名</span>
          <span className="text-zinc-200">{iface.iface_name}</span>
        </div>
        {iface.ip_address && (
          <div className="flex items-center gap-2">
            <span className="text-zinc-500 w-14 shrink-0">IP 地址</span>
            <span className="text-zinc-200">{iface.ip_address}</span>
          </div>
        )}
      </div>

      <div className="ml-5 flex items-center gap-3 mt-3">
        <span className={`text-[8px] px-2 py-0.5 border font-bold uppercase tracking-wider ${
          iface.enabled
            ? 'border-emerald-500/40 text-emerald-400'
            : 'border-zinc-700 text-zinc-500'
        }`}>
          {iface.enabled ? '已启用' : '已禁用'}
        </span>
        <span className="text-[8px] px-2 py-0.5 border border-zinc-700 text-zinc-500 font-bold uppercase tracking-wider">
          {{ robot: '机器人', camera: '摄像头', other: '其他' }[iface.purpose] || iface.purpose}
        </span>
      </div>
    </div>
  );

  // ── 渲染：视频源表单弹窗 ──────────────────────────────────
  const renderSourceFormModal = () => {
    if (!showSourceForm) return null;
    return (
      <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4" onClick={() => setShowSourceForm(false)}>
        <div
          className="bg-zinc-950 border border-zinc-700 w-full max-w-lg max-h-[85vh] overflow-y-auto custom-scrollbar"
          onClick={e => e.stopPropagation()}
        >
          {/* 标题 */}
          <div className="sticky top-0 bg-zinc-950 border-b border-zinc-800 px-5 py-3 flex items-center justify-between z-10">
            <span className="text-xs font-bold uppercase tracking-[0.2em]">
              {editingSourceId !== null ? '编辑视频源' : '新增视频源'}
            </span>
            <button onClick={() => setShowSourceForm(false)} className="text-zinc-400 hover:text-white transition-colors">
              <X size={14} />
            </button>
          </div>

          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <FormRow label="标识符 (name)">
                <TextInput value={sourceForm.name} onChange={v => setSourceForm(f => ({ ...f, name: v }))} placeholder="如 cam1" />
              </FormRow>
              <FormRow label="显示名称 (label)">
                <TextInput value={sourceForm.label} onChange={v => setSourceForm(f => ({ ...f, label: v }))} placeholder="如 USB 主摄像头" />
              </FormRow>
            </div>

            <FormRow label="类型">
              <select
                value={sourceForm.source_type}
                onChange={e => setSourceForm(f => ({ ...f, source_type: e.target.value }))}
                className="bg-zinc-950 border border-zinc-700 text-white font-mono text-xs px-3 py-2 focus:outline-none focus:border-white transition-all appearance-none uppercase tracking-wider w-full"
              >
                <option value="whep">WHEP (WebRTC)</option>
                <option value="rtsp">RTSP</option>
                <option value="usb">USB</option>
              </select>
            </FormRow>

            <FormRow label="WHEP 播放地址 (前端用)">
              <TextInput value={sourceForm.whep_url} onChange={v => setSourceForm(f => ({ ...f, whep_url: v }))} placeholder="http://192.168.x.x:8889/cam/whep" />
            </FormRow>

            <FormRow label="RTSP 拉流地址 (AI 推理用)">
              <TextInput value={sourceForm.rtsp_url} onChange={v => setSourceForm(f => ({ ...f, rtsp_url: v }))} placeholder="rtsp://127.0.0.1:8554/cam" />
            </FormRow>

            <FormRow label="排序序号">
              <input
                type="number"
                value={sourceForm.sort_order}
                onChange={e => setSourceForm(f => ({ ...f, sort_order: parseInt(e.target.value) || 0 }))}
                className="bg-zinc-950 border border-zinc-700 px-3 py-2 text-xs text-white font-mono focus:outline-none focus:border-white transition-all w-24"
              />
            </FormRow>

            <div className="flex items-center gap-8 pt-2 border-t border-zinc-800">
              <Toggle checked={sourceForm.enabled} onChange={v => setSourceForm(f => ({ ...f, enabled: v }))} label="启用" />
              <Toggle checked={sourceForm.is_primary} onChange={v => setSourceForm(f => ({ ...f, is_primary: v }))} label="主画面" />
              <Toggle checked={sourceForm.is_ai_source} onChange={v => setSourceForm(f => ({ ...f, is_ai_source: v }))} label="AI 源" />
            </div>

            {/* 保存按钮 */}
            <div className="flex justify-end gap-3 pt-4 border-t border-zinc-800">
              <button
                onClick={() => setShowSourceForm(false)}
                className="px-6 py-2 text-[10px] font-bold uppercase tracking-[0.2em] border border-zinc-600 text-zinc-300 hover:text-white hover:border-white transition-all"
              >取消</button>
              <button
                onClick={handleSaveSource}
                disabled={admin.loading || !sourceForm.name || !sourceForm.label}
                className="flex items-center gap-2 px-6 py-2 text-[10px] font-bold uppercase tracking-[0.2em] bg-white text-black hover:bg-zinc-200 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Save size={12} />
                {admin.loading ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  // ── 渲染：网口表单弹窗 ──────────────────────────────────
  const renderIfaceFormModal = () => {
    if (!showIfaceForm) return null;
    return (
      <div className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4" onClick={() => setShowIfaceForm(false)}>
        <div
          className="bg-zinc-950 border border-zinc-700 w-full max-w-lg max-h-[85vh] overflow-y-auto custom-scrollbar"
          onClick={e => e.stopPropagation()}
        >
          <div className="sticky top-0 bg-zinc-950 border-b border-zinc-800 px-5 py-3 flex items-center justify-between z-10">
            <span className="text-xs font-bold uppercase tracking-[0.2em]">
              {editingIfaceId !== null ? '编辑网口' : '新增网口'}
            </span>
            <button onClick={() => setShowIfaceForm(false)} className="text-zinc-400 hover:text-white transition-colors">
              <X size={14} />
            </button>
          </div>

          <div className="p-5 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <FormRow label="标识符 (name)">
                <TextInput value={ifaceForm.name} onChange={v => setIfaceForm(f => ({ ...f, name: v }))} placeholder="如 robot_link" />
              </FormRow>
              <FormRow label="显示名称 (label)">
                <TextInput value={ifaceForm.label} onChange={v => setIfaceForm(f => ({ ...f, label: v }))} placeholder="如 机器人连接网口" />
              </FormRow>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <FormRow label="系统网卡名">
                <TextInput value={ifaceForm.iface_name} onChange={v => setIfaceForm(f => ({ ...f, iface_name: v }))} placeholder="如 enP3p49s0" />
              </FormRow>
              <FormRow label="IP 地址">
                <TextInput value={ifaceForm.ip_address} onChange={v => setIfaceForm(f => ({ ...f, ip_address: v }))} placeholder="如 192.168.123.18" />
              </FormRow>
            </div>

            <FormRow label="用途">
              <select
                value={ifaceForm.purpose}
                onChange={e => setIfaceForm(f => ({ ...f, purpose: e.target.value }))}
                className="bg-zinc-950 border border-zinc-700 text-white font-mono text-xs px-3 py-2 focus:outline-none focus:border-white transition-all appearance-none uppercase tracking-wider w-full"
              >
                <option value="robot">机器人连接</option>
                <option value="camera">摄像头连接</option>
                <option value="other">其他</option>
              </select>
            </FormRow>

            <div className="pt-2 border-t border-zinc-800">
              <Toggle checked={ifaceForm.enabled} onChange={v => setIfaceForm(f => ({ ...f, enabled: v }))} label="启用" />
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t border-zinc-800">
              <button
                onClick={() => setShowIfaceForm(false)}
                className="px-6 py-2 text-[10px] font-bold uppercase tracking-[0.2em] border border-zinc-600 text-zinc-300 hover:text-white hover:border-white transition-all"
              >取消</button>
              <button
                onClick={handleSaveIface}
                disabled={admin.loading || !ifaceForm.name || !ifaceForm.label || !ifaceForm.iface_name}
                className="flex items-center gap-2 px-6 py-2 text-[10px] font-bold uppercase tracking-[0.2em] bg-white text-black hover:bg-zinc-200 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Save size={12} />
                {admin.loading ? '保存中...' : '保存'}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  // ── 主渲染 ──────────────────────────────────────────────
  const tabInfo: Record<AdminTab, { icon: React.ReactNode; label: string; count: number | null }> = {
    video:   { icon: <Video size={12} />,   label: '视频源管理', count: admin.sources.length },
    network: { icon: <Network size={12} />, label: '网口管理',   count: admin.interfaces.length },
    sysinfo: { icon: <Info size={12} />,    label: '系统信息',   count: null },
  };

  return (
    <div className="bg-black text-white font-mono flex flex-col w-full h-full max-h-[90vh]">
      {/* 顶部标题栏 */}
      <div className="sticky top-0 z-20 bg-black border-b border-zinc-800 flex items-center justify-between px-5 shrink-0" style={{ height: '48px' }}>
        <div className="flex items-center gap-5 min-w-0">
          <span className="text-xs tracking-[0.2em] font-bold border-r border-zinc-700 pr-5 uppercase whitespace-nowrap">
            BOTDOG // 后台管理
          </span>
          <span className="text-[10px] text-zinc-400 uppercase tracking-widest hidden md:block whitespace-nowrap">
            设备配置 // 运行时生效
          </span>
        </div>

        <div className="flex items-stretch h-full shrink-0">
          <button
            onClick={() => { admin.fetchSources(); admin.fetchInterfaces(); }}
            disabled={admin.loading}
            className="flex items-center gap-2 px-4 text-zinc-400 hover:text-white hover:bg-zinc-900 transition-all border-l border-zinc-800 disabled:opacity-40"
          >
            <RefreshCw size={12} className={admin.loading ? 'animate-spin' : ''} />
            <span className="text-[10px] font-bold uppercase tracking-[0.2em]">刷新</span>
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="flex items-center justify-center w-12 text-zinc-400 hover:text-white hover:bg-zinc-900 transition-all border-l border-zinc-800"
              title="关闭"
            >
              <X size={14} />
            </button>
          )}
        </div>
      </div>

      {/* 提示消息 */}
      {(admin.error || successMsg) && (
        <div className="border-b border-zinc-800 px-5 py-3 space-y-2 shrink-0 bg-black">
          {admin.error && (
            <div className="flex items-center gap-3 text-red-400 text-[10px] font-mono">
              <AlertTriangle size={12} className="shrink-0" />
              <span>{admin.error}</span>
            </div>
          )}
          {successMsg && (
            <div className="flex items-center gap-3 text-white text-[10px] font-mono bg-zinc-900 px-3 py-1.5 border border-zinc-700">
              <CheckCircle2 size={12} className="shrink-0" />
              <span>{successMsg}</span>
            </div>
          )}
        </div>
      )}

      {/* Tab 栏 */}
      <div className="sticky top-12 z-10 bg-black flex gap-px bg-zinc-900 border-b border-zinc-800 shrink-0">
        {(Object.entries(tabInfo) as [AdminTab, typeof tabInfo.video][]).map(([key, info]) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`flex-1 flex items-center justify-between px-4 py-3 text-[10px] transition-all ${
              activeTab === key
                ? 'bg-white text-black font-bold'
                : 'bg-black text-zinc-400 hover:text-white hover:bg-zinc-900'
            }`}
          >
            <div className="flex items-center gap-2">
              {info.icon}
              <span className="tracking-widest uppercase">{info.label}</span>
            </div>
            <span className="opacity-50 font-mono">
              {info.count !== null ? `[${String(info.count).padStart(2, '0')}]` : ''}
            </span>
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="overflow-y-auto custom-scrollbar flex-1">
        {/* ── 视频源列表 ── */}
        {activeTab === 'video' && (
          <>
            <div className="flex items-center justify-between border-b border-zinc-900 px-5 py-3 bg-black">
              <div className="flex items-center gap-2">
                <div className="w-0.5 h-4 bg-white" />
                <h2 className="text-xs font-bold tracking-widest uppercase">
                  视频源列表 // <span className="text-zinc-400">摄像头配置</span>
                </h2>
              </div>
              <button
                onClick={openNewSource}
                className="flex items-center gap-2 px-4 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] border border-zinc-600 text-zinc-300 hover:text-white hover:border-white hover:bg-zinc-900 transition-all"
              >
                <Plus size={12} />
                新增
              </button>
            </div>

            {admin.sources.length === 0 ? (
              <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
                <div className="w-12 h-12 border border-dashed border-zinc-700 flex items-center justify-center">
                  <Camera size={20} />
                </div>
                <span className="text-[10px] uppercase tracking-widest">暂无视频源配置</span>
                <button
                  onClick={openNewSource}
                  className="text-[10px] font-bold uppercase tracking-widest text-white border border-white px-4 py-1.5 hover:bg-white hover:text-black transition-all"
                >
                  添加第一个
                </button>
              </div>
            ) : (
              <div className="grid gap-px bg-zinc-900">
                {admin.sources.map(renderSourceCard)}
              </div>
            )}

            {/* 底部提示 */}
            <div className="px-5 py-3 border-t border-zinc-900 bg-black">
              <div className="flex items-center gap-2 text-[9px] font-mono text-zinc-600">
                <AlertTriangle size={10} />
                <span>修改视频源地址后，刷新前端页面即可生效。标记为「主画面」的视频源将作为主视频流显示。</span>
              </div>
            </div>
          </>
        )}

        {/* ── 网口列表 ── */}
        {activeTab === 'network' && (
          <>
            <div className="flex items-center justify-between border-b border-zinc-900 px-5 py-3 bg-black">
              <div className="flex items-center gap-2">
                <div className="w-0.5 h-4 bg-white" />
                <h2 className="text-xs font-bold tracking-widest uppercase">
                  网口列表 // <span className="text-zinc-400">网络接口配置</span>
                </h2>
              </div>
              <button
                onClick={openNewIface}
                className="flex items-center gap-2 px-4 py-1.5 text-[10px] font-bold uppercase tracking-[0.2em] border border-zinc-600 text-zinc-300 hover:text-white hover:border-white hover:bg-zinc-900 transition-all"
              >
                <Plus size={12} />
                新增
              </button>
            </div>

            {admin.interfaces.length === 0 ? (
              <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
                <div className="w-12 h-12 border border-dashed border-zinc-700 flex items-center justify-center">
                  <Wifi size={20} />
                </div>
                <span className="text-[10px] uppercase tracking-widest">暂无网口配置</span>
                <button
                  onClick={openNewIface}
                  className="text-[10px] font-bold uppercase tracking-widest text-white border border-white px-4 py-1.5 hover:bg-white hover:text-black transition-all"
                >
                  添加第一个
                </button>
              </div>
            ) : (
              <div className="grid gap-px bg-zinc-900">
                {admin.interfaces.map(renderIfaceCard)}
              </div>
            )}

            <div className="px-5 py-3 border-t border-zinc-900 bg-black">
              <div className="flex items-center gap-2 text-[9px] font-mono text-zinc-600">
                <AlertTriangle size={10} />
                <span>网口配置仅存储元信息（网卡名称、IP 地址），不会执行操作系统级别的网口启停命令。</span>
              </div>
            </div>
          </>
        )}

        {/* ── 系统信息（只读）── */}
        {activeTab === 'sysinfo' && (
          <>
            <div className="flex items-center justify-between border-b border-zinc-900 px-5 py-3 bg-black">
              <div className="flex items-center gap-2">
                <div className="w-0.5 h-4 bg-white" />
                <h2 className="text-xs font-bold tracking-widest uppercase">
                  系统硬件信息 // <span className="text-zinc-400">只读 · 来源 .env</span>
                </h2>
              </div>
              <span className="flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest border border-zinc-700 px-2 py-1 text-zinc-500">
                <Lock size={9} /> 只读
              </span>
            </div>

            {sysInfoLoading ? (
              <div className="py-16 flex items-center justify-center text-zinc-600 text-[10px] uppercase tracking-widest">
                加载中...
              </div>
            ) : (
              <div className="p-5 space-y-6">
                {sysInfo.map(group => (
                  <div key={group.group}>
                    {/* 分组标题 */}
                    <div className="flex items-center gap-3 mb-3">
                      <div className="w-0.5 h-3 bg-zinc-600" />
                      <span className="text-[9px] font-bold uppercase tracking-[0.25em] text-zinc-500">
                        {group.group}
                      </span>
                      <div className="flex-1 h-px bg-zinc-900" />
                    </div>

                    {/* 条目列表 */}
                    <div className="space-y-2">
                      {group.items.map(item => (
                        <div
                          key={item.key}
                          className="bg-zinc-950 border border-zinc-900 px-4 py-3 flex flex-col gap-1.5 hover:border-zinc-700 transition-colors"
                        >
                          <div className="flex items-center justify-between gap-4">
                            <span className="text-[9px] font-bold uppercase tracking-[0.18em] text-zinc-500 shrink-0">
                              {item.label}
                            </span>
                            {/* 来源标注 */}
                            {item.env_key !== '—' && (
                              <span className="text-[8px] font-mono text-zinc-700 border border-zinc-800 px-1.5 py-0.5 shrink-0">
                                {item.env_key}
                              </span>
                            )}
                          </div>
                          {/* 值 */}
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-mono font-bold text-white tracking-wide break-all">
                              {item.value}
                            </span>
                            {item.env_key === '—' && (
                              <span className="text-[8px] font-bold uppercase tracking-wider border border-zinc-800 px-1.5 py-0.5 text-zinc-600 shrink-0">
                                硬件固定
                              </span>
                            )}
                          </div>
                          {/* 说明 */}
                          <p className="text-[9px] text-zinc-600 font-mono leading-relaxed">
                            {item.note}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}

                {/* 底部提示 */}
                <div className="flex items-start gap-2 text-[9px] font-mono text-zinc-700 border-t border-zinc-900 pt-4">
                  <AlertTriangle size={10} className="shrink-0 mt-0.5" />
                  <span>
                    以上参数来源于部署时的 <code className="text-zinc-500">.env</code> 文件。
                    如需修改，请在 OrangePi 上编辑 <code className="text-zinc-500">backend/.env</code>
                    后重启后端服务生效。「硬件固定」项由硬件厂商出厂设定，无法通过软件修改。
                  </span>
                </div>
              </div>
            )}
          </>
        )}

        {/* 弹窗 */}
        {renderSourceFormModal()}
        {renderIfaceFormModal()}
      </div>
    </div>
  );
}
