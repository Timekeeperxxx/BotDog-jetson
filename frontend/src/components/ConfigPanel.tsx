/**
 * 工业风系统高级参数配置面板
 * 与主控制台保持一致的高端、暗黑工业美学风格。
 */

import { useState, useEffect, useRef } from 'react';
import { useConfig } from '../hooks/useConfig';
import type { SystemConfig } from '../types/config';
import { Settings, RefreshCw, History, Save, AlertTriangle, CheckCircle2 } from 'lucide-react';

export function ConfigPanel() {
  const configHook = useConfig();

  // UI 状态
  const [selectedCategory, setSelectedCategory] = useState<string>('backend');
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Refs 防止重渲染丢失输入焦点
  const inputRefs = useRef<Record<string, HTMLInputElement | HTMLSelectElement | null>>({});

  useEffect(() => {
    configHook.fetchConfigs();
  }, []);

  // 动态解析模块分类
  const allConfigs = Object.values(configHook.configs);
  const categories = Array.from(new Set(allConfigs.map(c => c.category)));
  
  const categoryNames: Record<string, string> = {
    backend: '核心节点',
    frontend: '界面终端',
    storage: '黑匣存储',
    auto_track: '猎眼 AI',
    camera: '周界感知',
    hardware: '机电调优',
    system: '底层基座',
    navigation: '领航系统'
  };

  const currentGroupConfigs = allConfigs.filter(c => c.category === selectedCategory);

  const handleSaveConfig = async (key: string, value: any) => {
    try {
      setValidationError(null);
      setSuccessMessage(null);

      const config = configHook.configs[key];
      const validation = configHook.validateConfig(key, value, config.value_type);

      if (!validation.valid) {
        setValidationError(validation.error || '参数验证阻断');
        return;
      }

      await configHook.updateConfig(key, value, '前端特权指令覆写');
      setSuccessMessage(`指令执行成功：参数 [${key}] 已重载`);

      setTimeout(() => setSuccessMessage(null), 3000);
      await configHook.fetchConfigs();
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : '协议传输异常');
    }
  };

  const handleShowHistory = async () => {
    try {
      const historyData = await configHook.fetchHistory();
      setHistory(historyData);
      setShowHistory(true);
    } catch (error) {
      console.error('档案提取失败:', error);
    }
  };

  const getConfigDisplayValue = (config: SystemConfig): string => {
    if (config.value_type === 'bool') return config.value ? '已激活 (ACTIVE)' : '已休眠 (DORMANT)';
    return String(config.value);
  };

  const renderConfigInput = (config: SystemConfig) => {
    if (config.value_type === 'bool') {
      const isChecked = Boolean(config.value);
      return (
        <label className="flex items-center space-x-3 cursor-pointer group">
          <div className="relative">
            <input
              type="checkbox"
              className="sr-only"
              checked={isChecked}
              onChange={(e) => handleSaveConfig(config.key, e.target.checked)}
              disabled={configHook.loading}
            />
            <div className={`block w-12 h-6 rounded-full transition-all border-2 border-black ${
              isChecked ? 'bg-emerald-500 shadow-[0_0_15px_rgba(16,185,129,0.5)]' : 'bg-slate-700'
            }`}></div>
            <div className={`absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform duration-300 ${
              isChecked ? 'transform translate-x-6' : ''
            }`}></div>
          </div>
          <span className={`text-xs font-black uppercase tracking-widest ${isChecked ? 'text-emerald-400' : 'text-slate-500'}`}>
            {isChecked ? 'Active' : 'Standby'}
          </span>
        </label>
      );
    }

    if (config.key === 'ui_lang') {
      return (
        <select
          value={config.value as string}
          onChange={(e) => handleSaveConfig(config.key, e.target.value)}
          disabled={configHook.loading}
          className="w-full bg-black/60 border border-white/20 text-white font-mono text-xs px-4 py-2.5 rounded-md focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 transition-all cursor-pointer uppercase tracking-wider"
        >
          <option value="zh-CN">简体中文 (ZH-CN)</option>
          <option value="en-US">English (EN-US)</option>
        </select>
      );
    }

    if (config.key === 'ui_theme') {
      return (
        <select
          value={config.value as string}
          onChange={(e) => handleSaveConfig(config.key, e.target.value)}
          disabled={configHook.loading}
          className="w-full bg-black/60 border border-white/20 text-white font-mono text-xs px-4 py-2.5 rounded-md focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 transition-all cursor-pointer uppercase tracking-wider"
        >
          <option value="dark">暗夜工业 (DARK)</option>
          <option value="light">耀眼极光 (LIGHT)</option>
        </select>
      );
    }

    // Number & String inputs
    const isNum = config.value_type === 'int' || config.value_type === 'float';
    return (
      <div className="flex space-x-3 w-full">
        <input
          ref={(el) => { inputRefs.current[config.key] = el; }}
          type={isNum ? "number" : "text"}
          step={config.value_type === 'float' ? '0.1' : '1'}
          defaultValue={config.value as string | number}
          disabled={configHook.loading}
          className="flex-1 bg-black/60 border border-white/20 text-white font-mono text-sm px-4 py-2.5 rounded-md focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500/50 transition-all placeholder-white/20"
          placeholder={`Enter ${config.value_type}...`}
        />
        <button
          onClick={() => {
            const el = inputRefs.current[config.key];
            if (el) handleSaveConfig(config.key, el.value);
          }}
          disabled={configHook.loading}
          className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white disabled:bg-slate-800 disabled:text-slate-500 font-black text-[11px] uppercase tracking-widest rounded-md border border-indigo-400/30 transition-all flex items-center justify-center min-w-[100px] shadow-[0_0_15px_rgba(79,70,229,0.3)] hover:shadow-[0_0_20px_rgba(79,70,229,0.5)]"
        >
          <Save size={14} className="mr-2" />
          {configHook.loading ? '执行中' : '写入 (OVR)'}
        </button>
      </div>
    );
  };

  const renderConfigItem = (config: SystemConfig) => (
    <div
      key={config.key}
      className="bg-black/40 border border-white/10 p-5 rounded-xl hover:border-white/30 transition-all duration-300 relative overflow-hidden group mb-4"
    >
      <div className="absolute top-0 left-0 w-1 h-full bg-indigo-500/30 group-hover:bg-indigo-400 transition-colors"></div>
      
      <div className="flex justify-between items-start mb-4">
        <div className="flex-1 pl-3">
          <div className="flex items-center space-x-3 mb-1.5">
            <span className="text-sm font-mono font-black text-white tracking-wide">{config.key}</span>
            {config.is_hot_reloadable ? (
              <span className="text-[9px] px-2 py-0.5 bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 rounded uppercase font-black tracking-widest">
                热重载 ACTIVE
              </span>
            ) : (
              <span className="text-[9px] px-2 py-0.5 bg-amber-500/20 text-amber-400 border border-amber-500/40 rounded uppercase font-black tracking-widest">
                需硬重启
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 font-bold leading-relaxed">{config.description}</p>
        </div>
      </div>

      <div className="pl-3">
        {renderConfigInput(config)}
        <div className="mt-3 flex items-center space-x-2">
          <span className="text-[9px] uppercase tracking-widest text-slate-600 font-black">CURR_STATE //</span>
          <span className="text-[10px] font-mono text-slate-300 bg-white/5 px-2 py-0.5 rounded border border-white/10">
            {getConfigDisplayValue(config)}
          </span>
          <span className="text-[9px] font-mono text-indigo-400/60 uppercase tracking-widest pl-2 border-l border-white/10">
            TYPE: {config.value_type}
          </span>
        </div>
      </div>
    </div>
  );

  return (
    <div className="bg-[#050506] border-2 border-white/10 rounded-xl overflow-hidden shadow-[0_20px_60px_rgba(0,0,0,0.8)] flex flex-col w-full text-white font-sans ring-1 ring-white/5">
      {/* 头部标题区 */}
      <div className="bg-zinc-900 border-b border-white/10 px-6 py-4 flex justify-between items-center relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/10 to-transparent pointer-events-none"></div>
        <div className="flex items-center space-x-3 relative z-10">
          <div className="w-8 h-8 rounded border border-indigo-500/50 bg-indigo-500/20 flex items-center justify-center shadow-[0_0_15px_rgba(79,70,229,0.3)]">
            <Settings size={16} className="text-indigo-300" />
          </div>
          <div>
            <h3 className="text-sm font-black text-white uppercase tracking-[0.2em] leading-tight">BotDog 高级参数矩阵</h3>
            <p className="text-[9px] font-mono text-slate-500 uppercase tracking-widest">System Configuration Panel // LEVEL-1 ACCESS</p>
          </div>
        </div>
        <button
          onClick={() => configHook.fetchConfigs()}
          disabled={configHook.loading}
          className="flex items-center space-x-2 px-3 py-1.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-md transition-all group z-10"
        >
          <RefreshCw size={12} className={`text-indigo-400 group-hover:text-indigo-300 ${configHook.loading ? 'animate-spin' : ''}`} />
          <span className="text-[10px] font-black uppercase tracking-widest text-slate-300 group-hover:text-white">SYS_SYNC</span>
        </button>
      </div>

      {/* 动态警报栏 */}
      <div className="px-6 pt-4">
        {configHook.error && (
          <div className="mb-4 p-3 bg-red-900/30 border-l-4 border-red-500 rounded-r-md flex items-center space-x-3">
            <AlertTriangle size={16} className="text-red-400 shrink-0" />
            <span className="text-xs font-mono text-red-200">{configHook.error}</span>
          </div>
        )}
        {successMessage && (
          <div className="mb-4 p-3 bg-emerald-900/30 border-l-4 border-emerald-500 rounded-r-md flex items-center space-x-3">
            <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
            <span className="text-xs font-mono text-emerald-200">{successMessage}</span>
          </div>
        )}
        {validationError && (
          <div className="mb-4 p-3 bg-amber-900/30 border-l-4 border-amber-500 rounded-r-md flex items-center space-x-3">
            <AlertTriangle size={16} className="text-amber-400 shrink-0" />
            <span className="text-xs font-mono text-amber-200">{validationError}</span>
          </div>
        )}
      </div>

      {/* 本体内容区 */}
      <div className="flex-1 flex flex-col p-6 pt-2">
        {/* 顶部标签页 */}
        <div className="flex flex-wrap gap-2 border-b border-white/10 pb-5 mb-5">
          {categories.map(cat => {
            const count = allConfigs.filter(c => c.category === cat).length;
            const isActive = selectedCategory === cat;
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`flex items-center space-x-2 px-4 py-2 rounded-md transition-all border ${
                  isActive 
                    ? 'bg-indigo-600/20 border-indigo-500/50 text-indigo-300 shadow-[0_0_15px_rgba(79,70,229,0.2)]' 
                    : 'bg-white/5 border-transparent text-slate-400 hover:bg-white/10 hover:text-white'
                }`}
              >
                <span className="text-[11px] font-black uppercase tracking-widest">{categoryNames[cat] || cat}</span>
                <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded ${isActive ? 'bg-indigo-500/30 text-indigo-200' : 'bg-black/50 text-slate-500'}`}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {/* 核心配置列表 */}
        <div className="max-h-[500px] overflow-y-auto pr-2 custom-scrollbar">
          {currentGroupConfigs.length === 0 ? (
            <div className="py-12 flex flex-col items-center justify-center opacity-50">
              <div className="w-16 h-16 border-2 border-dashed border-white/20 rounded-full flex items-center justify-center mb-4 animate-[spin_10s_linear_infinite]">
                <Settings size={24} className="text-white/40" />
              </div>
              <span className="text-xs font-mono uppercase tracking-widest text-slate-400">NO CONFIGS FOUND IN SECTOR</span>
            </div>
          ) : (
            currentGroupConfigs.map(config => renderConfigItem(config))
          )}
        </div>

        {/* 底部历史记录查阅 */}
        <div className="mt-6 pt-5 border-t border-white/10">
          <button
            onClick={handleShowHistory}
            disabled={showHistory}
            className={`w-full py-3 rounded-md font-black text-[11px] uppercase tracking-widest transition-all flex items-center justify-center space-x-2 ${
              showHistory 
                ? 'bg-zinc-900 border border-white/10 text-slate-500 cursor-not-allowed' 
                : 'bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700 hover:text-white hover:border-slate-500'
            }`}
          >
            <History size={14} />
            <span>查阅全局指令下发历史 (SYSTEM LOG)</span>
          </button>
          
          {showHistory && (
            <div className="mt-4 bg-[#0a0a0c] border border-indigo-500/30 rounded-lg p-5 relative">
              <div className="absolute top-0 right-0 p-3">
                <button 
                  onClick={() => setShowHistory(false)}
                  className="text-slate-500 hover:text-white transition-colors"
                >
                  <span className="sr-only">关闭历史</span>
                  ✕
                </button>
              </div>
              <h4 className="text-xs font-black text-indigo-400 uppercase tracking-widest mb-4 flex items-center">
                <History size={14} className="mr-2" />
                指令下发日志
              </h4>
              {history.length === 0 ? (
                <div className="py-6 text-center text-[10px] font-mono text-slate-500 uppercase">NO MODIFICATION LOGS FOUND</div>
              ) : (
                <div className="max-h-[250px] overflow-y-auto space-y-3 pr-2 custom-scrollbar">
                  {history.map(item => (
                    <div key={item.history_id} className="bg-black/40 border-l-2 border-indigo-500/50 p-3 rounded-r flex flex-col space-y-2">
                       <div className="flex items-center justify-between">
                         <span className="font-mono text-xs font-bold text-white">{item.config_key}</span>
                         <span className="text-[9px] font-mono text-slate-500 uppercase tracking-wider">{new Date(item.changed_at).toLocaleString('zh-CN', { hour12: false })}</span>
                       </div>
                       <div className="flex items-center space-x-3 text-xs font-mono bg-white/5 p-2 rounded border border-white/5">
                         <span className="text-slate-400 strike-through line-through opacity-70">{item.old_value}</span>
                         <span className="text-indigo-400">→</span>
                         <span className="text-emerald-400 font-bold">{item.new_value}</span>
                       </div>
                       <div className="flex items-center justify-between text-[10px]">
                         <span className="text-slate-500 uppercase tracking-widest">{item.changed_by}</span>
                         {item.reason && <span className="text-indigo-300/80 italic w-1/2 text-right truncate">"{item.reason}"</span>}
                       </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
