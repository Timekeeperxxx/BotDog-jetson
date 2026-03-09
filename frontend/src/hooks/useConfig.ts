/**
 * 配置 API Hook
 *
 * 管理系统配置的获取、更新和历史记录查询
 */

import { useState, useCallback } from 'react';
import type { SystemConfig, ConfigChangeHistory, ConfigValidationRule } from '../types/config';
import { getApiUrl } from '../config/api';

/**
 * 配置 API Hook
 *
 * @param baseURL 后端 API 基础 URL
 * @returns 配置管理状态和方法
 */
export function useConfig(baseURL?: string) {
  const apiUrl = baseURL || getApiUrl('');
  const [state, setState] = useState({
    configs: {} as Record<string, SystemConfig>,
    loading: false,
    error: null as string | null,
  });

  /**
   * 获取所有配置
   *
   * @param category 可选的类别过滤器
   * @returns 配置对象字典
   */
  const fetchConfigs = useCallback(async (category?: 'backend' | 'frontend' | 'storage') => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const url = category
        ? `${apiUrl}/api/v1/config?category=${category}`
        : `${apiUrl}/api/v1/config`;

      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`获取配置失败: ${response.status}`);
      }

      const data = await response.json();
      const configs = data.configs as Record<string, SystemConfig>;

      // 转换配置值的类型
      const typedConfigs: Record<string, SystemConfig> = {};
      for (const [key, config] of Object.entries(configs)) {
        typedConfigs[key] = {
          ...config,
          value: convertValue(config.value as string, config.value_type),
        };
      }

      setState(prev => ({
        ...prev,
        configs: typedConfigs,
        loading: false,
      }));

      return typedConfigs;
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '未知错误';
      setState(prev => ({
        ...prev,
        error: errorMsg,
        loading: false,
      }));
      throw error;
    }
  }, [baseURL]);

  /**
   * 更新配置
   *
   * @param key 配置键
   * @param value 新值
   * @param reason 可选的修改原因
   * @returns 更新后的配置对象
   */
  const updateConfig = useCallback(async (
    key: string,
    value: string | number | boolean,
    reason?: string
  ) => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const response = await fetch(`${apiUrl}/api/v1/config`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          key,
          value: String(value),
          changed_by: 'frontend_user',
          reason: reason || '通过前端界面更新',
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || '更新配置失败');
      }

      const data = await response.json();

      // 更新本地状态
      setState(prev => ({
        ...prev,
        configs: {
          ...prev.configs,
          [key]: {
            ...prev.configs[key],
            value: convertValue(data.config.value, data.config.value_type),
          },
        },
        loading: false,
      }));

      // 重新获取所有配置以保持同步
      await fetchConfigs();

      return data.config;
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '未知错误';
      setState(prev => ({
        ...prev,
        error: errorMsg,
        loading: false,
      }));
      throw error;
    }
  }, [baseURL, fetchConfigs]);

  /**
   * 获取配置历史
   *
   * @param key 可选的配置键过滤器
   * @param limit 返回的最大记录数
   * @returns 配置变更历史数组
   */
  const fetchHistory = useCallback(async (key?: string, limit: number = 50) => {
    try {
      const url = key
        ? `${apiUrl}/api/v1/config/history?key=${key}&limit=${limit}`
        : `${apiUrl}/api/v1/config/history?limit=${limit}`;

      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`获取配置历史失败: ${response.status}`);
      }

      const data = await response.json();
      return data.history as ConfigChangeHistory[];
    } catch (error) {
      console.error('获取配置历史失败:', error);
      return [];
    }
  }, [baseURL]);

  /**
   * 验证配置值
   *
   * @param key 配置键
   * @param value 待验证的值
   * @param valueType 值类型
   * @returns 验证结果
   */
  const validateConfig = useCallback((
    key: string,
    value: string | number | boolean,
    valueType: 'int' | 'float' | 'bool' | 'string'
  ): { valid: boolean; error?: string } => {
    // 获取验证规则
    const rules: Record<string, ConfigValidationRule> = {
      thermal_threshold: { min: 30, max: 120 },
      heartbeat_timeout: { min: 1, max: 10 },
      control_rate_limit_hz: { min: 5, max: 50 },
      ws_max_clients_per_ip: { min: 1, max: 20 },
      video_watchdog_timeout_s: { min: 1, max: 10 },
      ui_alert_ack_timeout_s: { min: 10, max: 600 },
      telemetry_display_hz: { min: 5, max: 30 },
      snapshot_retention_days: { min: 7, max: 365 },
      max_snapshot_disk_usage_gb: { min: 10, max: 500 },
      telemetry_retention_days: { min: 30, max: 365 },
      ui_lang: { options: ['zh-CN', 'en-US'] },
      ui_theme: { options: ['dark', 'light'] },
    };

    const rule = rules[key];
    if (!rule) return { valid: true };

    // 类型检查
    if (valueType === 'int' && !Number.isInteger(Number(value))) {
      return { valid: false, error: '必须是整数' };
    }

    if (valueType === 'float') {
      const num = Number(value);
      if (isNaN(num)) return { valid: false, error: '必须是数字' };
    }

    // 范围检查
    if (rule.min !== undefined && Number(value) < rule.min) {
      return { valid: false, error: `最小值为 ${rule.min}` };
    }

    if (rule.max !== undefined && Number(value) > rule.max) {
      return { valid: false, error: `最大值为 ${rule.max}` };
    }

    // 选项检查
    if (rule.options && !rule.options.includes(String(value))) {
      return { valid: false, error: `无效选项` };
    }

    return { valid: true };
  }, []);

  return {
    // 状态
    ...state,

    // 方法
    fetchConfigs,
    updateConfig,
    fetchHistory,
    validateConfig,
  };
}

/**
 * 转换配置值的类型
 *
 * @param value 字符串值
 * @param valueType 值类型
 * @returns 转换后的值
 */
function convertValue(value: string, valueType: 'int' | 'float' | 'bool' | 'string'): string | number | boolean {
  switch (valueType) {
    case 'int':
      return parseInt(value, 10);
    case 'float':
      return parseFloat(value);
    case 'bool':
      return value === 'true' || value === '1';
    case 'string':
    default:
      return value;
  }
}
