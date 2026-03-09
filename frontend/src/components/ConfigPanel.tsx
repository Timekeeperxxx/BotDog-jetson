/**
 * 系统配置面板组件
 *
 * 提供可视化的配置管理界面，支持按类别查看、编辑配置
 */

import { useState, useEffect, useRef } from 'react';
import { useConfig } from '../hooks/useConfig';
import type { ConfigCategory, ConfigGroup, SystemConfig } from '../types/config';

/**
 * 配置面板组件
 */
export function ConfigPanel() {
  const configHook = useConfig();

  // UI 状态
  const [selectedCategory, setSelectedCategory] = useState<ConfigCategory>('backend');
  const [showHistory, setShowHistory] = useState(false);
  const [history, setHistory] = useState<any[]>([]);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editValue, setEditValue] = useState<string | number | boolean>('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Refs
  const inputRefs = useRef<Record<string, HTMLInputElement | null>>({});

  // 加载配置
  useEffect(() => {
    configHook.fetchConfigs();
  }, []);

  // 配置分组
  const configGroups: ConfigGroup[] = [
    {
      name: 'backend',
      displayName: '后端配置',
      configs: Object.values(configHook.configs).filter(c => c.category === 'backend'),
    },
    {
      name: 'frontend',
      displayName: '前端配置',
      configs: Object.values(configHook.configs).filter(c => c.category === 'frontend'),
    },
    {
      name: 'storage',
      displayName: '存储配置',
      configs: Object.values(configHook.configs).filter(c => c.category === 'storage'),
    },
  ];

  // 获取当前选中的分组
  const currentGroup = configGroups.find(g => g.name === selectedCategory);

  /**
   * 处理保存配置
   */
  const handleSaveConfig = async (key: string, value: any) => {
    try {
      setValidationError(null);
      setSuccessMessage(null);

      // 验证输入
      const config = configHook.configs[key];
      const validation = configHook.validateConfig(key, value, config.value_type);

      if (!validation.valid) {
        setValidationError(validation.error || '验证失败');
        return;
      }

      // 更新配置
      await configHook.updateConfig(key, value, '通过前端界面更新');
      setSuccessMessage(`配置 ${key} 更新成功`);

      // 3秒后清除成功消息
      setTimeout(() => setSuccessMessage(null), 3000);

      // 重新加载配置
      await configHook.fetchConfigs();

      // 清除编辑状态
      setEditingKey(null);
      setEditValue('');
    } catch (error) {
      setValidationError(error instanceof Error ? error.message : '更新失败');
    }
  };

  /**
   * 处理查看历史
   */
  const handleShowHistory = async () => {
    try {
      const historyData = await configHook.fetchHistory();
      setHistory(historyData);
      setShowHistory(true);
    } catch (error) {
      console.error('获取配置历史失败:', error);
    }
  };

  /**
   * 获取配置的显示值
   */
  const getConfigDisplayValue = (config: SystemConfig): string => {
    if (config.value_type === 'bool') {
      return config.value ? '启用' : '禁用';
    }
    return String(config.value);
  };

  /**
   * 渲染配置项的输入控件
   */
  const renderConfigInput = (config: SystemConfig) => {
    const isEditing = editingKey === config.key;

    if (config.value_type === 'bool') {
      return (
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <input
            type="checkbox"
            checked={Boolean(config.value)}
            onChange={(e) => handleSaveConfig(config.key, e.target.checked)}
            style={{
              width: '16px',
              height: '16px',
              accentColor: '#3b82f6',
              cursor: 'pointer',
            }}
          />
          <span style={{ fontSize: '10px', color: '#94a3b8' }}>
            {Boolean(config.value) ? '启用' : '禁用'}
          </span>
        </label>
      );
    }

    if (config.key === 'ui_lang') {
      return (
        <select
          value={config.value as string}
          onChange={(e) => handleSaveConfig(config.key, e.target.value)}
          style={{
            width: '100%',
            padding: '8px 12px',
            background: 'rgba(0, 0, 0, 0.3)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            color: '#e2e8f0',
            fontSize: '13px',
            cursor: 'pointer',
          }}
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
          onChange={(e) => handleSaveConfig(config.key, e.target.value)}
          style={{
            width: '100%',
            padding: '8px 12px',
            background: 'rgba(0, 0, 0, 0.3)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            color: '#e2e8f0',
            fontSize: '13px',
            cursor: 'pointer',
          }}
        >
          <option value="dark">深色主题</option>
          <option value="light">浅色主题</option>
        </select>
      );
    }

    // 数值类型输入
    return (
      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          ref={(el) => { inputRefs.current[config.key] = el; }}
          type="number"
          step={config.value_type === 'float' ? '0.1' : '1'}
          defaultValue={config.value as number}
          disabled={configHook.loading}
          style={{
            flex: 1,
            padding: '8px 12px',
            background: 'rgba(0, 0, 0, 0.3)',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            color: '#e2e8f0',
            fontSize: '13px',
            disabled: configHook.loading ? { opacity: 0.5 } : undefined,
          }}
        />
        <button
          onClick={() => {
            const input = inputRefs.current[config.key];
            if (input) {
              handleSaveConfig(config.key, input.value);
            }
          }}
          disabled={configHook.loading}
          style={{
            padding: '8px 16px',
            background: '#3b82f6',
            border: 'none',
            borderRadius: '6px',
            color: '#fff',
            fontSize: '11px',
            fontWeight: 'bold',
            cursor: configHook.loading ? 'not-allowed' : 'pointer',
            opacity: configHook.loading ? 0.5 : 1,
          }}
        >
          {configHook.loading ? '保存中...' : '保存'}
        </button>
      </div>
    );
  };

  /**
   * 渲染单个配置项
   */
  const renderConfigItem = (config: SystemConfig) => {
    return (
      <div
        key={config.key}
        style={{
          padding: '12px',
          marginBottom: '8px',
          background: 'rgba(255, 255, 255, 0.02)',
          borderRadius: '4px',
          border: '1px solid rgba(255, 255, 255, 0.05)',
          transition: 'border-color 0.2s',
        }}
      >
        {/* 配置标题和描述 */}
        <div style={{ marginBottom: '8px' }}>
          <div style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '4px',
          }}>
            <div style={{ flex: 1 }}>
              <div style={{
                fontSize: '11px',
                fontWeight: 'bold',
                color: '#e2e8f0',
                marginBottom: '2px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}>
                {config.key}
                {config.is_hot_reloadable ? (
                  <span style={{
                    fontSize: '8px',
                    color: '#10b981',
                    padding: '2px 6px',
                    background: 'rgba(16, 185, 129, 0.2)',
                    borderRadius: '9999px',
                    fontWeight: 'bold',
                  }}>
                    热更新
                  </span>
                ) : (
                  <span style={{
                    fontSize: '8px',
                    color: '#f59e0b',
                    padding: '2px 6px',
                    background: 'rgba(245, 158, 11, 0.2)',
                    borderRadius: '9999px',
                    fontWeight: 'bold',
                  }}>
                    需重启
                  </span>
                )}
              </div>
              <div style={{
                fontSize: '9px',
                color: '#64748b',
              }}>
                {config.description}
              </div>
            </div>
          </div>
        </div>

        {/* 输入控件 */}
        {renderConfigInput(config)}

        {/* 当前值显示 */}
        <div style={{
          marginTop: '6px',
          fontSize: '8px',
          color: '#64748b',
        }}>
          当前值: {getConfigDisplayValue(config)} ({config.value_type})
        </div>
      </div>
    );
  };

  /**
   * 渲染配置历史
   */
  const renderHistory = () => {
    if (!showHistory) return null;

    return (
      <div style={{
        marginTop: '16px',
        padding: '12px',
        background: 'rgba(59, 130, 246, 0.05)',
        border: '1px solid rgba(59, 130, 246, 0.2)',
        borderRadius: '6px',
      }}>
        <h4 style={{
          fontSize: '11px',
          color: '#93c5fd',
          marginBottom: '8px',
          fontWeight: 'bold',
        }}>
          📜 配置变更历史
        </h4>
        {history.length === 0 ? (
          <div style={{ fontSize: '10px', color: '#64748b', padding: '12px 0' }}>
            暂无变更记录
          </div>
        ) : (
          <div style={{
            maxHeight: '200px',
            overflowY: 'auto',
            fontSize: '9px',
            color: '#94a3b8',
          }}>
            {history.map(item => (
              <div
                key={item.history_id}
                style={{
                  padding: '8px 0',
                  borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                }}
              >
                <div style={{ marginBottom: '4px' }}>
                  <span style={{
                    fontSize: '10px',
                    fontWeight: 'bold',
                    color: '#e2e8f0',
                  }}>
                    {item.config_key}
                  </span>
                  <span style={{ marginLeft: '8px', color: '#10b981' }}>
                    {item.old_value} → {item.new_value}
                  </span>
                </div>
                <div style={{ fontSize: '8px', color: '#64748b' }}>
                  {item.changed_by} · {new Date(item.changed_at).toLocaleString('zh-CN')}
                </div>
                {item.reason && (
                  <div style={{
                    fontSize: '8px',
                    color: '#94a3b8',
                    marginTop: '2px',
                    fontStyle: 'italic',
                  }}>
                    原因: {item.reason}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <button
          onClick={() => setShowHistory(false)}
          style={{
            marginTop: '8px',
            padding: '6px 12px',
            background: 'transparent',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '4px',
            color: '#94a3b8',
            fontSize: '10px',
            cursor: 'pointer',
          }}
        >
          关闭
        </button>
      </div>
    );
  };

  /**
   * 渲染主要内容
   */
  return (
    <div style={{
      background: 'rgba(26, 29, 35, 0.95)',
      border: '1px solid rgba(255, 255, 255, 0.1)',
      borderRadius: '8px',
      padding: '16px',
      color: '#f1f5f9',
    }}>
      {/* 标题 */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '16px',
      }}>
        <h3 style={{
          fontSize: '12px',
          fontWeight: 'bold',
          color: '#94a3b8',
          textTransform: 'uppercase',
          letterSpacing: '1.5px',
          margin: 0,
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}>
          <span style={{ fontSize: '16px' }}>⚙️</span>
          系统配置
        </h3>
        <button
          onClick={() => configHook.fetchConfigs()}
          disabled={configHook.loading}
          style={{
            padding: '6px 12px',
            background: 'rgba(59, 130, 246, 0.2)',
            border: '1px solid rgba(59, 130, 246, 0.4)',
            borderRadius: '4px',
            color: '#93c5fd',
            fontSize: '10px',
            fontWeight: 'bold',
            cursor: configHook.loading ? 'not-allowed' : 'pointer',
            opacity: configHook.loading ? 0.5 : 1,
          }}
        >
          {configHook.loading ? '刷新中...' : '🔄 刷新'}
        </button>
      </div>

      {/* 类别切换 */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
        {configGroups.map(group => (
          <button
            key={group.name}
            onClick={() => setSelectedCategory(group.name)}
            style={{
              padding: '8px 16px',
              border: `1px solid ${selectedCategory === group.name ? '#3b82f6' : 'rgba(255, 255, 255, 0.1)'}`,
              borderRadius: '6px',
              background: selectedCategory === group.name
                ? '#3b82f6'
                : 'rgba(255, 255, 255, 0.05)',
              color: selectedCategory === group.name
                ? '#fff'
                : '#94a3b8',
              fontSize: '11px',
              fontWeight: 'bold',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            {group.displayName}
            <span style={{
              marginLeft: '6px',
              fontSize: '9px',
              opacity: 0.7,
            }}>
              ({group.configs.length})
            </span>
          </button>
        ))}
      </div>

      {/* 状态消息 */}
      {configHook.error && (
        <div style={{
          marginBottom: '12px',
          padding: '8px',
          background: 'rgba(239, 68, 68, 0.1)',
          border: '1px solid rgba(239, 68, 68, 0.3)',
          borderRadius: '4px',
          fontSize: '9px',
          color: '#fca5a5',
        }}>
          ❌ {configHook.error}
        </div>
      )}

      {successMessage && (
        <div style={{
          marginBottom: '12px',
          padding: '8px',
          background: 'rgba(16, 185, 129, 0.1)',
          border: '1px solid rgba(16, 185, 129, 0.3)',
          borderRadius: '4px',
          fontSize: '9px',
          color: '#6ee7b7',
        }}>
          ✅ {successMessage}
        </div>
      )}

      {validationError && (
        <div style={{
          marginBottom: '12px',
          padding: '8px',
          background: 'rgba(245, 158, 11, 0.1)',
          border: '1px solid rgba(245, 158, 11, 0.3)',
          borderRadius: '4px',
          fontSize: '9px',
          color: '#fcd34d',
        }}>
          ⚠️ {validationError}
        </div>
      )}

      {/* 配置列表 */}
      <div style={{
        maxHeight: '500px',
        overflowY: 'auto',
        paddingRight: '8px',
      }}>
        {currentGroup?.configs.length === 0 ? (
          <div style={{
            padding: '24px',
            textAlign: 'center',
            color: '#64748b',
            fontSize: '10px',
          }}>
            {configHook.loading ? '加载配置中...' : '暂无配置项'}
          </div>
        ) : (
          currentGroup?.configs.map(config => renderConfigItem(config))
        )}
      </div>

      {/* 配置历史按钮 */}
      <div style={{
        marginTop: '16px',
        paddingTop: '12px',
        borderTop: '1px solid rgba(255, 255, 255, 0.05)',
      }}>
        <button
          onClick={handleShowHistory}
          disabled={showHistory}
          style={{
            width: '100%',
            padding: '10px',
            background: 'rgba(59, 130, 246, 0.1)',
            border: '1px solid rgba(59, 130, 246, 0.3)',
            borderRadius: '6px',
            color: '#93c5fd',
            fontSize: '11px',
            fontWeight: 'bold',
            cursor: showHistory ? 'not-allowed' : 'pointer',
            opacity: showHistory ? 0.5 : 1,
          }}
        >
          📜 查看变更历史
        </button>
      </div>

      {/* 配置历史 */}
      {renderHistory()}
    </div>
  );
}
