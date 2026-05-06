import {
  Camera,
  FileSearch,
  HardDrive,
  LayoutDashboard,
  MapPinned,
  RefreshCw,
  ScrollText,
  Settings2,
  ShieldAlert,
  Users,
} from 'lucide-react'
import type { AdminMenuItem, AdminRole } from './components/AdminSidebar'

export const adminNavItems: AdminMenuItem[] = [
  { key: 'dashboard', label: '系统总览', icon: <LayoutDashboard size={18} />, description: '服务状态 / 告警 / 最新日志', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'control', label: '运行控制', icon: <ShieldAlert size={18} />, description: '控制入口 / 安全状态 / 当前目标', visibleTo: ['operator', 'admin'] },
  { key: 'navigation', label: '导航管理', icon: <MapPinned size={18} />, description: '地图 / 点位 / 巡逻任务', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'device-video', label: '设备与视频', icon: <HardDrive size={18} />, description: '主机信息 / 视频源 / 网络', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'ai-guard', label: 'AI 与驱离', icon: <Camera size={18} />, description: 'AI 状态 / 自动跟踪 / 驱离摘要', visibleTo: ['operator', 'admin'] },
  { key: 'evidence', label: '证据中心', icon: <FileSearch size={18} />, description: '证据记录 / 删除确认', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'logs', label: '日志审计', icon: <ScrollText size={18} />, description: '日志筛选 / 搜索 / 复制', visibleTo: ['viewer', 'operator', 'admin'] },
  { key: 'config', label: '系统配置', icon: <Settings2 size={18} />, description: '系统参数 / 热更新 / 历史', visibleTo: ['operator', 'admin'], badge: '只读' },
  { key: 'users', label: '用户与权限', icon: <Users size={18} />, description: '管理账号 / 角色 / 密码', visibleTo: ['admin'] },
  { key: 'diagnostics', label: '诊断工具', icon: <RefreshCw size={18} />, description: '安全 / 目标 / 登录态排查', visibleTo: ['viewer', 'operator', 'admin'] },
]

export function getVisibleSections(role: AdminRole) {
  return adminNavItems.filter((item) => item.visibleTo.includes(role)).map((item) => item.key)
}
