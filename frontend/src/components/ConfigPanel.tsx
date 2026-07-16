/**
 * 系统参数配置面板。
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
  const [search, setSearch] = useState('');
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
  const categoryOrder = [
    'backend',
    'hardware',
    'control',
    'ai',
    'auto_track',
    'guard',
    'navigation',
    'ros',
    'logging',
    'storage',
    'frontend',
    'frontend_draw',
    'zone',
  ];
  const categories = Array.from(new Set(allConfigs.map(c => c.category)))
    .sort((a, b) => {
      const ia = categoryOrder.indexOf(a);
      const ib = categoryOrder.indexOf(b);
      if (ia === -1 && ib === -1) return a.localeCompare(b);
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    });
  const adminOnlyTitle = canAdmin ? undefined : '需要 admin 权限';

  const categoryNames: Record<string, string> = {
    backend: '后端参数',
    hardware: '硬件连接',
    control: '运动控制',
    ai: 'AI 推理',
    auto_track: '自动跟踪',
    guard: '驱离任务',
    navigation: '地图与导航',
    ros: 'ROS2 导航',
    logging: '日志管理',
    frontend: '界面参数',
    frontend_draw: '区域绘制',
    storage: '存储参数',
    zone: '黄区识别',
    camera: '摄像参数',
    system: '系统参数',
  };

  const currentCategoryConfigs = allConfigs.filter(c => c.category === selectedCategory);
  const normalizedSearch = search.trim().toLowerCase();
  const currentGroupConfigs = currentCategoryConfigs.filter(config => (
    !normalizedSearch
    || config.key.toLowerCase().includes(normalizedSearch)
    || config.description.toLowerCase().includes(normalizedSearch)
  ));

  // 如果新旧值相同，不弹确认，不发请求
  const requestSaveConfig = (key: string, newValue: string | number | boolean) => {
    const config = configHook.configs[key];
    if (!config) return;
    const oldStr = String(config.value);
    const newStr = String(newValue);
    if (oldStr === newStr) return;
    const validation = configHook.validateConfig(key, newValue, config.value_type, config.validation);
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
      const validation = configHook.validateConfig(key, value, config.value_type, config.validation);

      if (!validation.valid) {
        setValidationError(validation.error || '参数验证阻断');
        return;
      }

      const result = await configHook.updateConfig(key, value, '后台配置中心修改');
      const runtimeApply = result.runtime_apply;
      if (runtimeApply?.applied) {
        if (runtimeApply.target === 'frontend') {
          setSuccessMessage('已保存，前端刷新配置后生效');
        } else {
          setSuccessMessage(`已保存，运行时已生效：${runtimeApply.message}`);
        }
      } else if (!config.is_hot_reloadable) {
        setSuccessMessage(`已保存，${runtimeApply?.message || '需重启后端生效'}`);
      } else {
        setSuccessMessage(`已保存，但运行时未生效：${runtimeApply?.message || '配置已更新'}`);
      }
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
      console.error('获取修改记录失败:', error);
    }
  };

  const getConfigDisplayValue = (config: SystemConfig): string => {
    if (config.value_type === 'bool') return config.value ? '已启用' : '已禁用';
    return String(config.value);
  };

  const renderConfigInput = (config: SystemConfig) => {
    if (config.value_type === 'bool') {
      const isChecked = Boolean(config.value);
      return (
        <div className="flex items-center">
          <label className="flex cursor-pointer items-center gap-3 text-sm text-zinc-300">
            <span className="relative">
              <input
                type="checkbox"
                className="peer sr-only"
                checked={isChecked}
                onChange={(e) => requestSaveConfig(config.key, e.target.checked)}
                disabled={configHook.loading || !canAdmin}
                title={adminOnlyTitle}
              />
              <span className={`block h-5 w-9 rounded-full border transition-colors peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-sky-600 ${
                isChecked ? 'border-sky-600 bg-sky-600' : 'border-zinc-600 bg-zinc-800'
              }`} />
              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                isChecked ? 'translate-x-[18px]' : 'translate-x-[2px]'
              }`} />
            </span>
            <span className={isChecked ? 'text-zinc-100' : 'text-zinc-400'}>
              {isChecked ? '启用' : '禁用'}
            </span>
          </label>
        </div>
      );
    }

    if (config.key === 'ui_lang') {
      return (
        <select
          value={config.value as string}
          onChange={(e) => requestSaveConfig(config.key, e.target.value)}
          disabled={configHook.loading || !canAdmin}
          title={adminOnlyTitle}
          className="w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none transition-colors focus:border-sky-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <option value="zh-CN">简体中文</option>
          <option value="en-US">English</option>
        </select>
      );
    }

    if (config.key === 'ui_theme') {
      return (
        <select
          value={config.value as string}
          onChange={(e) => requestSaveConfig(config.key, e.target.value)}
          disabled={configHook.loading || !canAdmin}
          title={adminOnlyTitle}
          className="w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none transition-colors focus:border-sky-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <option value="dark">深色</option>
          <option value="light">浅色</option>
        </select>
      );
    }

    if (config.validation?.options) {
      return (
        <select
          value={String(config.value)}
          onChange={(e) => requestSaveConfig(config.key, e.target.value)}
          disabled={configHook.loading || !canAdmin}
          title={adminOnlyTitle}
          className="w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none transition-colors focus:border-sky-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {config.validation.options.map(option => (
            <option key={String(option)} value={String(option)}>
              {String(option) || '不压缩'}
            </option>
          ))}
        </select>
      );
    }

    const isNum = config.value_type === 'int' || config.value_type === 'float';
    return (
      <div className="flex items-center gap-2">
        <input
          ref={(el) => { inputRefs.current[config.key] = el; }}
          type={isNum ? 'number' : 'text'}
          step={config.value_type === 'float' ? '0.1' : '1'}
          defaultValue={config.value as string | number}
          disabled={configHook.loading || !canAdmin}
          title={adminOnlyTitle}
          className="min-w-0 flex-1 rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 font-mono text-sm text-white outline-none transition-colors placeholder:text-zinc-600 focus:border-sky-600 disabled:cursor-not-allowed disabled:opacity-40"
          placeholder={`输入${config.value_type === 'string' ? '文本' : '数值'}`}
        />
        <button
          type="button"
          onClick={() => {
            const el = inputRefs.current[config.key];
            if (el) requestSaveConfig(config.key, el.value);
          }}
          disabled={configHook.loading || !canAdmin}
          title={adminOnlyTitle}
          className="shrink-0 rounded-md border border-white/12 bg-[#1b2026] px-3 py-2 text-sm font-medium text-zinc-100 transition-colors hover:border-white/25 hover:bg-[#222831] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {configHook.loading ? '保存中' : '保存'}
        </button>
      </div>
    );
  };

  const renderConfigItem = (config: SystemConfig) => (
    <div key={config.key} className="rounded-md border border-white/8 bg-[#11151a] p-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.9fr)] xl:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="break-all font-mono text-sm font-semibold text-zinc-100">
              {config.key}
            </span>
            <span className={`rounded border px-2 py-0.5 text-xs font-medium ${
              config.is_hot_reloadable
                ? 'border-emerald-700/60 bg-emerald-950/50 text-emerald-300'
                : 'border-amber-700/60 bg-amber-950/50 text-amber-300'
            }`}>
              {config.is_hot_reloadable ? '热更新' : '需重启'}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-zinc-400">{config.description}</p>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
            <span>类型：{config.value_type}</span>
            <span>当前值：<span className="font-mono text-zinc-300">{getConfigDisplayValue(config)}</span></span>
          </div>
        </div>
        <div className="xl:pt-0.5">
          {renderConfigInput(config)}
        </div>
      </div>
    </div>
  );

  return (
    <>
      <div className={`flex w-full flex-col bg-[#15191e] text-white ${
        onClose
          ? 'max-h-[85vh] rounded-lg border border-white/10'
          : 'max-h-[calc(100vh-180px)]'
      }`}>
        <div className="z-20 flex min-h-12 shrink-0 items-center justify-between border-b border-white/8 bg-[#15191e] px-5 py-2">
          <div className="min-w-0">
            <div className="text-sm font-semibold text-white">配置参数</div>
            <div className="mt-0.5 text-xs text-zinc-400">
              {canAdmin ? '管理员可修改配置' : '当前账号仅可查看'}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => configHook.fetchConfigs()}
              disabled={configHook.loading}
              className="flex items-center gap-2 rounded-md border border-white/12 bg-[#1b2026] px-3 py-2 text-sm font-medium text-zinc-100 transition-colors hover:border-white/25 hover:bg-[#222831] disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RefreshCw size={14} className={configHook.loading ? 'animate-spin' : ''} />
              <span>{configHook.loading ? '刷新中' : '刷新'}</span>
            </button>

            {onClose && (
              <button
                type="button"
                onClick={onClose}
                className="flex h-9 w-9 items-center justify-center rounded-md border border-white/12 text-zinc-400 transition-colors hover:border-white/25 hover:bg-white/5 hover:text-white"
                title="关闭"
                aria-label="关闭配置面板"
              >
                <X size={14} />
              </button>
            )}
          </div>
        </div>

        <div className="shrink-0 border-b border-amber-900/50 bg-amber-950/25 px-5 py-3">
          <div className="flex items-start gap-2.5 text-sm text-amber-200">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-400" />
            <div className="leading-6">
              <span className="font-medium">请勿随意修改系统配置。</span>
              <span className="ml-1 text-amber-200/80">
                错误参数可能影响设备控制、导航和服务稳定性；修改前请确认参数含义并记录原值，标记“需重启”的配置将在后端重启后生效。
              </span>
            </div>
          </div>
        </div>

        {(configHook.error || successMessage || validationError) && (
          <div className="shrink-0 space-y-2 border-b border-white/8 bg-[#11151a] px-5 py-3">
            {configHook.error && (
              <div className="flex items-center gap-2 rounded-md border border-red-800/60 bg-red-950/40 px-3 py-2 text-sm text-red-300">
                <AlertTriangle size={14} className="shrink-0" />
                <span>{configHook.error}</span>
              </div>
            )}
            {successMessage && (
              <div className="flex items-center gap-2 rounded-md border border-emerald-800/60 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-300">
                <CheckCircle2 size={14} className="shrink-0" />
                <span>{successMessage}</span>
              </div>
            )}
            {validationError && (
              <div className="flex items-center gap-2 rounded-md border border-amber-800/60 bg-amber-950/40 px-3 py-2 text-sm text-amber-300">
                <AlertTriangle size={14} className="shrink-0" />
                <span>{validationError}</span>
              </div>
            )}
          </div>
        )}

        <div className="z-10 flex shrink-0 gap-1 overflow-x-auto border-b border-white/8 bg-[#15191e] px-4">
          {categories.map(cat => {
            const count = allConfigs.filter(c => c.category === cat).length;
            const isActive = selectedCategory === cat;
            return (
              <button
                key={cat}
                type="button"
                onClick={() => {
                  setSelectedCategory(cat);
                  setSearch('');
                }}
                className={`flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm transition-colors ${
                  isActive
                    ? 'border-sky-500 text-white'
                    : 'border-transparent text-zinc-400 hover:border-white/20 hover:text-zinc-100'
                }`}
              >
                <span>{categoryNames[cat] || cat}</span>
                <span className="rounded bg-white/5 px-1.5 py-0.5 text-xs text-zinc-500">{count}</span>
              </button>
            );
          })}
        </div>

        <div className="custom-scrollbar flex-1 overflow-y-auto">
          <div className="flex flex-col gap-3 border-b border-white/8 bg-[#11151a] px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-sm font-medium text-zinc-200">
                {categoryNames[selectedCategory] || selectedCategory}
              </h2>
              <span className="mt-1 block text-xs text-zinc-500">
                {normalizedSearch
                  ? `找到 ${currentGroupConfigs.length} / ${currentCategoryConfigs.length} 个参数`
                  : `共 ${currentCategoryConfigs.length} 个参数`}
              </span>
            </div>
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="搜索参数名或说明"
              className="w-full rounded-md border border-white/10 bg-[#0d1014] px-3 py-2 text-sm text-white outline-none placeholder:text-zinc-600 focus:border-sky-600 sm:w-64"
            />
          </div>

          {currentGroupConfigs.length === 0 ? (
            <div className="flex items-center justify-center px-5 py-12 text-sm text-zinc-500">
              当前分类暂无参数
            </div>
          ) : (
            <div className="space-y-2 p-4">
              {currentGroupConfigs.map(config => renderConfigItem(config))}
            </div>
          )}

          <div className="border-t border-white/8">
            <button
              type="button"
              onClick={handleShowHistory}
              disabled={showHistory}
              className={`flex w-full items-center justify-center gap-2 px-4 py-3 text-sm transition-colors ${
                showHistory
                  ? 'cursor-not-allowed text-zinc-600'
                  : 'text-zinc-400 hover:bg-white/3 hover:text-white'
              }`}
            >
              <History size={14} />
              <span>查看修改记录</span>
            </button>

            {showHistory && (
              <div className="border-t border-white/8 bg-[#11151a] p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium text-zinc-200">
                    <History size={14} />
                    <span>修改记录</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowHistory(false)}
                    className="rounded p-1 text-zinc-400 transition-colors hover:bg-white/5 hover:text-white"
                    title="关闭"
                    aria-label="关闭修改记录"
                  >
                    <X size={14} />
                  </button>
                </div>
                {history.length === 0 ? (
                  <div className="rounded-md border border-dashed border-white/10 py-6 text-center text-sm text-zinc-500">
                    暂无修改记录
                  </div>
                ) : (
                  <div className="custom-scrollbar max-h-64 space-y-2 overflow-y-auto">
                    {history.map(item => (
                      <div key={item.history_id} className="rounded-md border border-white/8 bg-[#15191e] px-4 py-3">
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-sm font-medium text-white">{item.config_key}</span>
                          <span className="text-xs text-zinc-500">
                            {new Date(item.changed_at).toLocaleString('zh-CN', { hour12: false })}
                          </span>
                        </div>
                        <div className="mt-2 flex items-center gap-3 rounded bg-[#0d1014] px-3 py-2 font-mono text-xs">
                          <span className="text-zinc-500 line-through">{item.old_value}</span>
                          <span className="text-zinc-400">→</span>
                          <span className="font-medium text-white">{item.new_value}</span>
                        </div>
                        <div className="mt-2 flex items-center justify-between gap-3 text-xs">
                          <span className="text-zinc-500">操作人：{item.changed_by}</span>
                          {item.reason && (
                            <span className="max-w-[60%] truncate text-right text-zinc-400">{item.reason}</span>
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

      {pendingSave !== null && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center bg-black/75 px-4">
          <div className="w-full max-w-md rounded-lg border border-white/12 bg-[#15191e] p-5 shadow-xl">
            <div className="text-lg font-semibold text-white">确认修改配置</div>
            <div className="mt-4 space-y-3 text-sm">
              <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <span className="text-zinc-500">配置项</span>
                <span className="break-all font-mono text-white">{pendingSave.key}</span>
              </div>
              <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <span className="text-zinc-500">修改前</span>
                <span className="break-all font-mono text-zinc-300 line-through">{String(pendingSave.oldValue)}</span>
              </div>
              <div className="grid grid-cols-[72px_minmax(0,1fr)] gap-2">
                <span className="text-zinc-500">修改后</span>
                <span className="break-all font-mono font-medium text-white">{String(pendingSave.newValue)}</span>
              </div>
              <div className={`mt-3 rounded-md border px-3 py-2 text-sm leading-6 ${
                pendingSave.isHotReloadable
                  ? 'border-emerald-800/60 bg-emerald-950/40 text-emerald-300'
                  : 'border-amber-800/60 bg-amber-950/40 text-amber-300'
              }`}>
                {pendingSave.isHotReloadable
                  ? '该配置支持热更新，保存后立即生效。'
                  : '该配置需要重启后端服务才能生效，可能影响当前运行行为。'}
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-md border border-white/12 bg-[#1b2026] px-3 py-2 text-sm font-medium text-zinc-100 transition-colors hover:border-white/25 hover:bg-[#222831]"
                onClick={() => setPendingSave(null)}
              >取消</button>
              <button
                type="button"
                className="rounded-md border border-sky-600 bg-sky-600 px-3 py-2 text-sm font-medium text-white transition-colors hover:border-sky-500 hover:bg-sky-500"
                onClick={() => {
                  const { key, newValue } = pendingSave;
                  setPendingSave(null);
                  void handleSaveConfig(key, newValue);
                }}
              >确认保存</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
