/**
 * BOTDOG // CONFIG_MATRIX
 * 系统参数配置终端 - 工业硬核风格
 */

import { useState, useEffect, useRef } from 'react';
import { useConfig } from '../hooks/useConfig';
import type { ConfigChangeHistory, SystemConfig } from '../types/config';
import { RefreshCw, History, AlertTriangle, CheckCircle2, X } from 'lucide-react';
import { hasAuthSession, hasRole, useAuthState } from '../stores/authStore';

interface ConfigPanelProps {
  onClose?: () => void;
  configHook?: ReturnType<typeof useConfig>;
}

export function ConfigPanel({ onClose, configHook: externalConfigHook }: ConfigPanelProps) {
  useAuthState();
  const canAdmin = hasAuthSession() && hasRole('admin');
  const localConfigHook = useConfig();
  const configHook = externalConfigHook ?? localConfigHook;
  const { fetchConfigs } = configHook;

  const [selectedCategory, setSelectedCategory] = useState<string>('backend');
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<ConfigChangeHistory[]>([]);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  // 高危操作确认
  const [pendingSave, setPendingSave] = useState<{
    key: string;
    oldValue: string | number | boolean;
    newValue: string | number | boolean;
    isHotReloadable: boolean;
  } | null>(null);

  const inputRefs = useRef<Record<string, HTMLInputElement | HTMLSelectElement | null>>({});

  useEffect(() => {
    if (externalConfigHook) return;
    void fetchConfigs();
  }, [externalConfigHook, fetchConfigs]);

  const allConfigs = Object.values(configHook.configs);
  const categories = Array.from(new Set(allConfigs.map(c => c.category)));
  const adminOnlyTitle = canAdmin ? undefined : '需要 admin 权限';

  const categoryNames: Record<string, string> = {
    backend: '后端参数',
    frontend: '界面参数',
    storage: '存储参数',
    auto_track: 'AI 参数',
    camera: '摄像参数',
    hardware: '硬件参数',
    system: '系统参数',
    navigation: '导航参数',
  };

  const currentGroupConfigs = allConfigs.filter(c => c.category === selectedCategory);

  // 如果新旧值相同，不弹确认，不发请求
  const requestSaveConfig = (key: string, newValue: string | number | boolean) => {
    const config = configHook.configs[key];
    if (!config) return;
    const oldStr = String(config.value);
    const newStr = String(newValue);
    if (oldStr === newStr) return;
    const validation = configHook.validateConfig(key, newValue, config.value_type);
    if (!validation.valid) {
      setValidationError(validation.error || '参数验证阻断');
      return;
    }
    setPendingSave({ key, oldValue: config.value, newValue, isHotReloadable: config.is_hot_reloadable });
  };

  const handleSaveConfig = async (key: string, value: string | number | boolean) => {
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
    if (config.value_type === 'bool') return config.value ? '已激活' : '已休眠';
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
                onChange={(e) => requestSaveConfig(config.key, e.target.checked)}
                disabled={configHook.loading || !canAdmin}
                title={adminOnlyTitle}
              />
              <div className={`w-10 h-5 border transition-all ${
                isChecked ? 'bg-white border-white' : 'bg-zinc-900 border-zinc-600'
              }`} />
              <div className={`absolute top-0.5 w-4 h-4 transition-transform duration-200 ${
                isChecked ? 'translate-x-5 bg-black' : 'translate-x-0.5 bg-zinc-500'
              }`} />
            </div>
            <span className={`text-[10px] font-bold uppercase tracking-[0.2em] ${
              isChecked ? 'text-white' : 'text-zinc-400'
            }`}>
              {isChecked ? '已启用' : '已禁用'}
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
              onChange={(e) => requestSaveConfig(config.key, e.target.value)}
              disabled={configHook.loading || !canAdmin}
              title={adminOnlyTitle}
              className="flex-1 bg-zinc-950 border border-zinc-700 text-white font-mono text-xs px-4 py-2 focus:outline-none focus:border-white transition-all appearance-none uppercase tracking-wider"
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
              onChange={(e) => requestSaveConfig(config.key, e.target.value)}
              disabled={configHook.loading || !canAdmin}
              title={adminOnlyTitle}
              className="flex-1 bg-zinc-950 border border-zinc-700 text-white font-mono text-xs px-4 py-2 focus:outline-none focus:border-white transition-all appearance-none uppercase tracking-wider"
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
          disabled={configHook.loading || !canAdmin}
          title={adminOnlyTitle}
          className="flex-1 bg-zinc-950 border border-zinc-700 px-4 py-2 text-sm text-white font-mono focus:outline-none focus:border-white transition-all placeholder-zinc-500"
          placeholder={`输入 ${config.value_type}...`}
        />
        <button
          onClick={() => {
            const el = inputRefs.current[config.key];
            if (el) requestSaveConfig(config.key, el.value);
          }}
          disabled={configHook.loading || !canAdmin}
          title={adminOnlyTitle}
          className="bg-zinc-800 border border-zinc-600 text-white px-5 py-2 text-[10px] font-bold uppercase tracking-[0.2em] hover:bg-white hover:text-black hover:border-white transition-all disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {configHook.loading ? '写入中' : '写入'}
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
            <div className="w-0.5 h-4 bg-zinc-600 group-hover:bg-white transition-colors shrink-0" />
            <span className="text-sm font-bold tracking-widest uppercase text-zinc-200 group-hover:text-white transition-colors truncate font-mono">
              {config.key}
            </span>
            <span className={`text-[8px] px-2 py-0.5 border font-bold shrink-0 uppercase tracking-wider ${
              config.is_hot_reloadable
                ? 'border-zinc-700 text-zinc-400'
                : 'border-white text-white'
            }`}>
              {config.is_hot_reloadable ? '热重载' : '需重启'}
            </span>
          </div>
        </div>

        {/* 描述 */}
        <div className="text-[11px] text-zinc-300 ml-3 tracking-tight font-mono">
          // {config.description}
        </div>

        {/* 输入区 */}
        <div className="ml-3">
          {renderConfigInput(config)}
        </div>

        {/* 底部元信息 */}
        <div className="ml-3 flex items-center gap-6 text-[9px] text-zinc-500 uppercase border-t border-zinc-900 pt-3 font-bold tracking-widest">
          <span>当前值: <span className="text-zinc-300">{getConfigDisplayValue(config)}</span></span>
          <span>类型: {config.value_type.toUpperCase()}</span>
          <span>REF: 0x{config.key.slice(0, 4).toUpperCase()}</span>
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className="bg-black text-white font-mono flex flex-col w-full border border-zinc-800 max-h-[90vh]">

        {/* ① 顶部标题栏 - sticky，不随内容滚动消失 */}
        <div className="sticky top-0 z-20 bg-black border-b border-zinc-800 flex items-center justify-between px-5 shrink-0" style={{ height: '48px' }}>
          <div className="flex items-center gap-5 min-w-0">
            <span className="text-xs tracking-[0.2em] font-bold border-r border-zinc-700 pr-5 uppercase whitespace-nowrap">
              BOTDOG // 参数矩阵
            </span>
            <span className="text-[10px] text-zinc-400 uppercase tracking-widest hidden md:block whitespace-nowrap">
              访问权限: 已授权 // LVL_1
            </span>
          </div>

          {/* 右侧操作区：刷新 | 关闭 各自独立，中间有明显间距 */}
          <div className="flex items-stretch h-full shrink-0">
            <button
              onClick={() => configHook.fetchConfigs()}
              disabled={configHook.loading}
              className="flex items-center gap-2 px-4 text-zinc-400 hover:text-white hover:bg-zinc-900 transition-all border-l border-zinc-800 disabled:opacity-40"
            >
              <RefreshCw size={12} className={configHook.loading ? 'animate-spin' : ''} />
              <span className="text-[10px] font-bold uppercase tracking-[0.2em]">刷新同步</span>
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

        {/* 告警/成功提示栏 */}
        {(configHook.error || successMessage || validationError) && (
          <div className="border-b border-zinc-800 px-5 py-3 space-y-2 shrink-0 bg-black">
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
              <div className="flex items-center gap-3 text-zinc-300 text-[10px] font-mono">
                <AlertTriangle size={12} className="shrink-0" />
                <span>{validationError}</span>
              </div>
            )}
          </div>
        )}

        {/* ② 分类 Tab - 也 sticky，紧贴 header 下方 */}
        <div className="sticky top-12 z-10 bg-black flex gap-px bg-zinc-900 border-b border-zinc-800 shrink-0">
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
                    : 'bg-black text-zinc-400 hover:text-white hover:bg-zinc-900'
                }`}
              >
                <span className="tracking-widest uppercase">{categoryNames[cat] || cat}</span>
                <span className="opacity-50 font-mono">[{String(count).padStart(2, '0')}]</span>
              </button>
            );
          })}
        </div>

        {/* ③ 可滚动内容区，header 和 tab 保持不动 */}
        <div className="overflow-y-auto custom-scrollbar flex-1">
          {/* 参数列表标题行 */}
          <div className="flex items-center justify-between border-b border-zinc-900 px-5 py-3 bg-black">
            <div className="flex items-center gap-2">
              <div className="w-0.5 h-4 bg-white" />
              <h2 className="text-xs font-bold tracking-widest uppercase">
                参数配置 // <span className="text-zinc-400">{categoryNames[selectedCategory] || selectedCategory}</span>
              </h2>
            </div>
            <span className="text-[9px] text-zinc-500 uppercase tracking-widest">
              共 {currentGroupConfigs.length} 个参数
            </span>
          </div>

          {currentGroupConfigs.length === 0 ? (
            <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
              <div className="w-12 h-12 border border-dashed border-zinc-700 flex items-center justify-center">
                <span className="text-lg">∅</span>
              </div>
              <span className="text-[10px] uppercase tracking-widest">当前分类无参数</span>
            </div>
          ) : (
            <div className="grid gap-px bg-zinc-900">
              {currentGroupConfigs.map(config => renderConfigItem(config))}
            </div>
          )}

          {/* 历史记录区 */}
          <div className="border-t border-zinc-900">
            <button
              onClick={handleShowHistory}
              disabled={showHistory}
              className={`w-full py-3 flex items-center justify-center gap-2 text-[10px] font-bold uppercase tracking-[0.2em] transition-all ${
                showHistory
                  ? 'text-zinc-600 cursor-not-allowed bg-black'
                  : 'text-zinc-400 hover:text-white hover:bg-zinc-950 bg-black'
              }`}
            >
              <History size={12} />
              <span>查阅指令下发历史</span>
            </button>

            {showHistory && (
              <div className="border-t border-zinc-900 bg-black p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-widest text-zinc-300">
                    <History size={11} />
                    <span>修改记录</span>
                  </div>
                  <button
                    onClick={() => setShowHistory(false)}
                    className="text-zinc-400 hover:text-white transition-colors p-1"
                    title="关闭"
                  >
                    <X size={12} />
                  </button>
                </div>
                {history.length === 0 ? (
                  <div className="py-4 text-center text-[9px] font-mono text-zinc-500 uppercase border border-zinc-800">
                    暂无修改记录
                  </div>
                ) : (
                  <div className="max-h-52 overflow-y-auto space-y-px bg-zinc-900 custom-scrollbar">
                    {history.map(item => (
                      <div key={item.history_id} className="bg-black px-4 py-3 flex flex-col gap-1.5 group hover:bg-zinc-950">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs font-bold text-white uppercase">{item.config_key}</span>
                          <span className="text-[9px] font-mono text-zinc-400">
                            {new Date(item.changed_at).toLocaleString('zh-CN', { hour12: false })}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-[10px] font-mono bg-zinc-950 px-3 py-1.5">
                          <span className="text-zinc-500 line-through">{item.old_value}</span>
                          <span className="text-zinc-400">→</span>
                          <span className="text-white font-bold">{item.new_value}</span>
                        </div>
                        <div className="flex items-center justify-between text-[9px]">
                          <span className="text-zinc-500 uppercase tracking-widest">{item.changed_by}</span>
                          {item.reason && (
                            <span className="text-zinc-400 italic truncate max-w-[60%] text-right">"{item.reason}"</span>
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

      {/* ─── 保存配置确认弹窗 ─── */}
      {pendingSave !== null && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-md bg-zinc-950 border border-white/10 p-6 rounded-2xl shadow-[0_30px_120px_-30px_rgba(0,0,0,0.9)] font-mono">
            <div className="text-base font-black text-white uppercase tracking-widest">确认修改配置</div>
            <div className="mt-4 space-y-2 text-xs">
              <div>
                <span className="text-zinc-500 uppercase tracking-wider">配置项：</span>
                <span className="text-white font-bold">{pendingSave.key}</span>
              </div>
              <div>
                <span className="text-zinc-500 uppercase tracking-wider">修改前：</span>
                <span className="text-zinc-300 line-through">{String(pendingSave.oldValue)}</span>
              </div>
              <div>
                <span className="text-zinc-500 uppercase tracking-wider">修改后：</span>
                <span className="text-white font-bold">{String(pendingSave.newValue)}</span>
              </div>
              <div className={`mt-3 px-3 py-2 border text-[10px] ${
                pendingSave.isHotReloadable
                  ? 'border-zinc-700 text-zinc-400'
                  : 'border-amber-500/40 bg-amber-500/5 text-amber-300'
              }`}>
                {pendingSave.isHotReloadable
                  ? '✓ 热重载项：修改将立即生效，无需重启。'
                  : '⚠ 需重启项：修改后需重启后端服务才能生效。修改运行中的配置可能影响当前运行行为。'}
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-3">
              <button
                className="bg-zinc-800 border border-zinc-600 text-white px-5 py-2 text-[10px] font-bold uppercase tracking-[0.2em] hover:bg-zinc-700 transition-all"
                onClick={() => setPendingSave(null)}
              >取消</button>
              <button
                className="bg-white text-black border border-white px-5 py-2 text-[10px] font-bold uppercase tracking-[0.2em] hover:bg-zinc-100 transition-all"
                onClick={() => {
                  const { key, newValue } = pendingSave;
                  setPendingSave(null);
                  void handleSaveConfig(key, newValue);
                }}
              >确认写入</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
