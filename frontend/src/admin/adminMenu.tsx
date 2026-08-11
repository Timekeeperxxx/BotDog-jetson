import {
  BrainCircuit,
  Camera,
  FileSearch,
  LayoutDashboard,
  MapPinned,
  RefreshCw,
  ScrollText,
  Settings2,
  ScanFace,
  ShieldAlert,
  Users,
} from 'lucide-react'
import type { AdminMenuItem, AdminRole } from './components/AdminSidebar'

export const adminNavItems: AdminMenuItem[] = [
  { key: 'dashboard', label: '系统总览', icon: <LayoutDashboard size={18} />, description: '主机资源 / 设备 / 服务状态', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'control', label: '运行控制', icon: <ShieldAlert size={18} />, description: '控制入口 / 安全状态 / 当前目标', visibleTo: [] },
  { key: 'navigation', label: '导航管理', icon: <MapPinned size={18} />, description: '场景 / 点位 / 任务', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'device-video', label: '视频与 AI', icon: <Camera size={18} />, description: '视频源 / AI 参数', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'ai-guard', label: 'AI 与驱离', icon: <Camera size={18} />, description: 'AI 状态 / 自动跟踪 / 驱离摘要', visibleTo: [] },
  { key: 'evidence', label: '证据中心', icon: <FileSearch size={18} />, description: '证据记录 / 删除确认', visibleTo: [] },
  { key: 'logs', label: '日志中心', icon: <ScrollText size={18} />, description: '审计日志 / 运行日志', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'config', label: '系统配置', icon: <Settings2 size={18} />, description: '系统参数 / 热更新 / 历史', visibleTo: ['operator', 'admin'], badge: '只读' },
  { key: 'users', label: '用户与权限', icon: <Users size={18} />, description: '管理账号 / 角色 / 密码', visibleTo: ['admin'] },
  { key: 'face-identities', label: '人员识别库', icon: <ScanFace size={18} />, description: '人员姓名 / 人脸模板', visibleTo: ['admin'] },
  { key: 'model-tester', label: '模型测试', icon: <BrainCircuit size={18} />, description: '图片 / 视频 / 离线推理', visibleTo: ['admin'] },
  { key: 'diagnostics', label: '诊断工具', icon: <RefreshCw size={18} />, description: '安全 / 目标 / 登录态排查', visibleTo: [] },
]

export function getVisibleSections(role: AdminRole) {
  return adminNavItems.filter((item) => item.visibleTo.includes(role)).map((item) => item.key)
}
