/**
 * BOTDOG // CONFIG_MATRIX
 * 系统参数配置终端 - 工业硬核风格
 */

import { useState, useEffect, useRef } from 'react';
import { useConfig } from '../hooks/useConfig';
import type { SystemConfig } from '../types/config';
import { RefreshCw, History, AlertTriangle, CheckCircle2 } from 'lucide-react';

export function ConfigPanel() {
  const configHook = useConfig();

  const [selectedCategory, setSelectedCategory] = useState<string>('backend');
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const inputRefs = useRef<Record<string, HTMLInputElement | HTMLSelectElement | null>>({});

  useEffect(() => {
    configHook.fetchConfigs();
  }, []);

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
    navigation: '领航系统',
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
    if (config.value_type === 'bool') return config.value ? 'ACTIVE' : 'DORMANT';
    return String(config.value);
  };

  const renderConfigInput = (config: SystemConfig) => {
    if (config.value_type === 'bool') {
      const isChecked = Boolean(config.value);
      return (
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-3 cursor-pointer">
            <div className="relative">
              <input
                type="checkbox"
                className="sr-only"
                checked={isChecked}
                onChange={(e) => handleSaveConfig(config.key, e.target.checked)}
                disabled={configHook.loading}
              />
              <div className={`w-10 h-5 border transition-all ${
                isChecked ? 'bg-white border-white' : 'bg-zinc-900 border-zinc-700'
              }`} />
              <div className={`absolute top-0.5 w-4 h-4 transition-transform duration-200 ${
                isChecked ? 'translate-x-5 bg-black' : 'translate-x-0.5 bg-zinc-600'
              }`} />
            </div>
            <span className={`text-[10px] font-bold uppercase tracking-[0.2em] ${
              isChecked ? 'text-white' : 'text-zinc-600'
            }`}>
              {isChecked ? 'ENABLED' : 'DISABLED'}
            </span>
          </label>
        </div>
      );
    }

    if (config.key === 'ui_lang') {
      return (
        <div className="flex items-center gap-3">
          <select
            value={config.value as string}
            onChange={(e) => handleSaveConfig(config.key, e.target.value)}
            disabled={configHook.loading}
            className="flex-1 bg-zinc-950 border border-zinc-800 text-white font-mono text-xs px-4 py-2 focus:outline-none focus:border-white transition-all appearance-none uppercase tracking-wider"
          >
            <option value="zh-CN">简体中文 (ZH-CN)</option>
            <option value="en-US">English (EN-US)</option>
          </select>
        </div>
      );
    }

    if (config.key === 'ui_theme') {
      return (
        <div className="flex items-center gap-3">
          <select
            value={config.value as string}
            onChange={(e) => handleSaveConfig(config.key, e.target.value)}
            disabled={configHook.loading}
            className="flex-1 bg-zinc-950 border border-zinc-800 text-white font-mono text-xs px-4 py-2 focus:outline-none focus:border-white transition-all appearance-none uppercase tracking-wider"
          >
            <option value="dark">暗夜工业 (DARK)</option>
            <option value="light">耀眼极光 (LIGHT)</option>
          </select>
        </div>
      );
    }

    const isNum = config.value_type === 'int' || config.value_type === 'float';
    return (
      <div className="flex items-center gap-3">
        <input
          ref={(el) => { inputRefs.current[config.key] = el; }}
          type={isNum ? 'number' : 'text'}
          step={config.value_type === 'float' ? '0.1' : '1'}
          defaultValue={config.value as string | number}
          disabled={configHook.loading}
          className="flex-1 bg-zinc-950 border border-zinc-800 px-4 py-2 text-sm text-white font-mono focus:outline-none focus:border-white transition-all placeholder-zinc-700"
          placeholder={`Enter ${config.value_type}...`}
        />
        <button
          onClick={() => {
            const el = inputRefs.current[config.key];
            if (el) handleSaveConfig(config.key, el.value);
          }}
          disabled={configHook.loading}
          className="bg-zinc-900 border border-zinc-700 text-white px-5 py-2 text-[10px] font-bold uppercase tracking-[0.2em] hover:bg-white hover:text-black hover:border-white transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {configHook.loading ? '...' : 'Write'}
        </button>
      </div>
    );
  };

  const renderConfigItem = (config: SystemConfig) => (
    <div key={config.key} className="bg-black p-5 group hover:bg-zinc-950 transition-colors">
      <div className="flex flex-col gap-4">
        {/* 顶部：参数名 + 类型标签 */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-0.5 h-4 bg-zinc-700 group-hover:bg-white transition-colors shrink-0" />
            <span className="text-sm font-bold tracking-widest uppercase text-zinc-300 group-hover:text-white transition-colors truncate font-mono">
              {config.key}
            </span>
            <span className={`text-[8px] px-2 py-0.5 border font-bold shrink-0 uppercase tracking-wider ${
              config.is_hot_reloadable
                ? 'border-zinc-800 text-zinc-500'
                : 'border-white text-white'
            }`}>
              {config.is_hot_reloadable ? 'HOT_SYNC' : 'REBOOT_REQ'}
            </span>
          </div>
        </div>

        {/* 描述 */}
        <div className="text-[11px] text-zinc-600 ml-3 tracking-tight font-mono">
          // {config.description}
        </div>

        {/* 输入区 */}
        <div className="ml-3">
          {renderConfigInput(config)}
        </div>

        {/* 底部元信息 */}
        <div className="ml-3 flex items-center gap-6 text-[9px] text-zinc-800 uppercase border-t border-zinc-900 pt-3 font-bold tracking-widest">
          <span>CURR: <span className="text-zinc-500">{getConfigDisplayValue(config)}</span></span>
          <span>TYPE: {config.value_type.toUpperCase()}</span>
          <span>REF: 0x{config.key.slice(0, 4).toUpperCase()}</span>
        </div>
      </div>
    </div>
  );

  return (
    <div className="bg-black text-white font-mono flex flex-col w-full border border-zinc-800">
      {/* 顶部标题栏 */}
      <div className="h-12 border-b border-zinc-800 flex items-center justify-between px-5 bg-black shrink-0">
        <div className="flex items-center gap-5">
          <span className="text-xs tracking-[0.2em] font-bold border-r border-zinc-800 pr-5 uppercase">
            BOTDOG // CONFIG_MATRIX
          </span>
          <span className="text-[10px] text-zinc-600 uppercase tracking-widest hidden md:block">
            Authorization: GRANTED // LVL_1_ACCESS
          </span>
        </div>
        <button
          onClick={() => configHook.fetchConfigs()}
          disabled={configHook.loading}
          className="flex items-center gap-2 px-3 h-full text-zinc-500 hover:text-white hover:bg-zinc-900 transition-all border-l border-zinc-800 disabled:opacity-40"
        >
          <RefreshCw size={12} className={configHook.loading ? 'animate-spin' : ''} />
          <span className="text-[10px] font-bold uppercase tracking-[0.2em]">SYS_SYNC</span>
        </button>
      </div>

      {/* 告警/成功提示栏 */}
      {(configHook.error || successMessage || validationError) && (
        <div className="border-b border-zinc-900 px-5 py-3 space-y-2">
          {configHook.error && (
            <div className="flex items-center gap-3 text-red-400 text-[10px] font-mono">
              <AlertTriangle size={12} className="shrink-0" />
              <span>{configHook.error}</span>
            </div>
          )}
          {successMessage && (
            <div className="flex items-center gap-3 text-white text-[10px] font-mono bg-zinc-900 px-3 py-1.5 border border-zinc-700">
              <CheckCircle2 size={12} className="shrink-0" />
              <span>{successMessage}</span>
            </div>
          )}
          {validationError && (
            <div className="flex items-center gap-3 text-zinc-400 text-[10px] font-mono">
              <AlertTriangle size={12} className="shrink-0" />
              <span>{validationError}</span>
            </div>
          )}
        </div>
      )}

      {/* 分类 Tab */}
      <div className="flex gap-px bg-zinc-900 border-b border-zinc-800 shrink-0">
        {categories.map(cat => {
          const count = allConfigs.filter(c => c.category === cat).length;
          const isActive = selectedCategory === cat;
          return (
            <button
              key={cat}
              onClick={() => setSelectedCategory(cat)}
              className={`flex-1 flex items-center justify-between px-3 py-3 text-[10px] transition-all ${
                isActive
                  ? 'bg-white text-black font-bold'
                  : 'bg-black text-zinc-500 hover:text-white hover:bg-zinc-950'
              }`}
            >
              <span className="tracking-widest uppercase">{categoryNames[cat] || cat}</span>
              <span className="opacity-40 font-mono">[{String(count).padStart(2, '0')}]</span>
            </button>
          );
        })}
      </div>

      {/* 参数列表 */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="flex items-center justify-between border-b border-zinc-900 px-5 py-3 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-0.5 h-4 bg-white" />
            <h2 className="text-xs font-bold tracking-widest uppercase">
              Configuration // <span className="text-zinc-500">{categoryNames[selectedCategory] || selectedCategory}</span>
            </h2>
          </div>
          <span className="text-[9px] text-zinc-700 uppercase tracking-widest">
            {currentGroupConfigs.length} PARAMS LOADED
          </span>
        </div>

        <div className="overflow-y-auto custom-scrollbar flex-1">
          {currentGroupConfigs.length === 0 ? (
            <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-700">
              <div className="w-12 h-12 border border-dashed border-zinc-800 flex items-center justify-center">
                <span className="text-lg">∅</span>
              </div>
              <span className="text-[10px] uppercase tracking-widest">NO CONFIGS IN SECTOR</span>
            </div>
          ) : (
            <div className="grid gap-px bg-zinc-900">
              {currentGroupConfigs.map(config => renderConfigItem(config))}
            </div>
          )}
        </div>

        {/* 历史记录区 */}
        <div className="border-t border-zinc-900 shrink-0">
          <button
            onClick={handleShowHistory}
            disabled={showHistory}
            className={`w-full py-3 flex items-center justify-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] transition-all ${
              showHistory
                ? 'text-zinc-700 cursor-not-allowed bg-black'
                : 'text-zinc-500 hover:text-white hover:bg-zinc-950 bg-black'
            }`}
          >
            <History size={12} />
            <span>查阅指令下发历史 (SYSTEM LOG)</span>
          </button>

          {showHistory && (
            <div className="border-t border-zinc-900 bg-black p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest">
                  <History size={11} />
                  <span>MODIFICATION LOG</span>
                </div>
                <button
                  onClick={() => setShowHistory(false)}
                  className="text-zinc-600 hover:text-white text-xs transition-colors"
                >
                  [CLOSE]
                </button>
              </div>
              {history.length === 0 ? (
                <div className="py-4 text-center text-[9px] font-mono text-zinc-700 uppercase border border-zinc-900">
                  NO MODIFICATION LOGS FOUND
                </div>
              ) : (
                <div className="max-h-52 overflow-y-auto space-y-px bg-zinc-900 custom-scrollbar">
                  {history.map(item => (
                    <div key={item.history_id} className="bg-black px-4 py-3 flex flex-col gap-1.5 group hover:bg-zinc-950">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs font-bold text-white uppercase">{item.config_key}</span>
                        <span className="text-[9px] font-mono text-zinc-600">
                          {new Date(item.changed_at).toLocaleString('zh-CN', { hour12: false })}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-[10px] font-mono bg-zinc-950 px-3 py-1.5">
                        <span className="text-zinc-600 line-through">{item.old_value}</span>
                        <span className="text-zinc-500">→</span>
                        <span className="text-white font-bold">{item.new_value}</span>
                      </div>
                      <div className="flex items-center justify-between text-[9px]">
                        <span className="text-zinc-700 uppercase tracking-widest">{item.changed_by}</span>
                        {item.reason && (
                          <span className="text-zinc-600 italic truncate max-w-[60%] text-right">"{item.reason}"</span>
                        )}
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
