import type { ReactNode } from 'react';
import { Activity, Bell, Database, History, LayoutGrid, Map, Settings, ShieldCheck } from 'lucide-react';
import type { AlertEvent } from '../../types/event';

export type SidebarTab = 'console' | 'history' | 'simulate' | 'admin' | 'guard';

interface SidebarBtnProps {
  icon: ReactNode;
  active: boolean;
  onClick?: () => void;
  label: string;
  dot?: boolean;
}

function SidebarBtn({ icon, active, onClick, label, dot }: SidebarBtnProps) {
  return (
    <div
      onClick={onClick}
      className={`relative p-3 rounded-lg cursor-pointer transition-all duration-200 group ${
        active
          ? 'bg-white text-black shadow-[0_0_20px_rgba(255,255,255,0.3)]'
          : 'text-slate-400 hover:text-white hover:bg-zinc-900'
      }`}
    >
      {icon}
      {dot && <div className="absolute top-2 right-2 w-2 h-2 bg-red-600 rounded-full border-2 border-black" />}
      <div className="absolute left-16 opacity-0 group-hover:opacity-100 pointer-events-none bg-white text-black border-2 border-white px-3 py-1.5 rounded text-[10px] uppercase font-black whitespace-nowrap transition-all transform group-hover:translate-x-1 z-[100]">
        {label}
      </div>
    </div>
  );
}

export interface SidebarProps {
  activeTab: SidebarTab;
  onTabChange: (tab: SidebarTab) => void;
  onOpenNavPatrolPage: () => void;
  onOpenConfig: () => void;
  latestAlert: AlertEvent | null;
  isUiFullscreen: boolean;
}

export function Sidebar({
  activeTab,
  onTabChange,
  onOpenNavPatrolPage,
  onOpenConfig,
  latestAlert,
  isUiFullscreen,
}: SidebarProps) {
  if (isUiFullscreen) return null;

  return (
    <nav className="w-14 flex flex-col items-center py-6 bg-black border-r border-white/20 z-50 shadow-2xl">
      <div className="w-9 h-9 border-2 border-white rounded-sm flex items-center justify-center mb-10 group cursor-pointer hover:bg-white transition-all">
        <Activity size={18} className="text-white group-hover:text-black" />
      </div>
      <div className="flex-1 flex flex-col space-y-5">
        <SidebarBtn icon={<LayoutGrid size={20} />} active={activeTab === 'console'} onClick={() => onTabChange('console')} label="控制台" />
        <SidebarBtn icon={<Map size={20} />} active={false} onClick={onOpenNavPatrolPage} label="导航巡逻" />
        <SidebarBtn icon={<ShieldCheck size={20} />} active={activeTab === 'guard'} onClick={() => onTabChange('guard')} label="驱离系统" />
        <SidebarBtn icon={<History size={20} />} active={activeTab === 'history'} onClick={() => onTabChange('history')} label="档案库" />
        <SidebarBtn icon={<Database size={20} />} active={activeTab === 'admin'} onClick={() => onTabChange('admin')} label="后台管理" />
      </div>
      <div className="mt-auto space-y-5 pt-4 border-t border-white/10">
        <SidebarBtn icon={<Settings size={20} />} active={false} onClick={onOpenConfig} label="设置" />
        <SidebarBtn icon={<Bell size={20} />} active={false} dot={!!latestAlert} label="告警" />
      </div>
    </nav>
  );
}
