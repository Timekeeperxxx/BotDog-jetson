/**
 * 配置 API Hook
 *
 * 管理系统配置的获取、更新和历史记录查询
 */

import { useState, useCallback } from 'react';
import type {
  SystemConfig,
  ConfigChangeHistory,
  ConfigValidationRule,
  ConfigCategory,
  ConfigUpdateResponse,
} from '../types/config';
import { apiFetch } from '../api/apiFetch';

/**
 * 配置 API Hook
 *
 * @returns 配置管理状态和方法
 */
export function useConfig() {
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
  const fetchConfigs = useCallback(async (category?: ConfigCategory) => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const data = await apiFetch<{ configs: Record<string, SystemConfig> }>(
        category ? `/api/v1/config?category=${category}` : '/api/v1/config',
      );
      const configs = data.configs as Record<string, SystemConfig>;

      // 转换配置值的类型
      const typedConfigs: Record<string, SystemConfig> = {};
      for (const [key, config] of Object.entries(configs)) {
        typedConfigs[key] = {
          ...config,
          value: convertValue(config.value, config.value_type),
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
  }, []);

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
    reason?: string,
  ) => {
    setState(prev => ({ ...prev, loading: true, error: null }));

    try {
      const data = await apiFetch<ConfigUpdateResponse>('/api/v1/config', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          key,
          value: String(value),
          reason: reason || '通过前端界面更新',
        }),
      });

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

      return data;
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : '未知错误';
      setState(prev => ({
        ...prev,
        error: errorMsg,
        loading: false,
      }));
      throw error;
    }
  }, []);

  /**
   * 获取配置历史
   *
   * @param key 可选的配置键过滤器
   * @param limit 返回的最大记录数
   * @returns 配置变更历史数组
   */
  const fetchHistory = useCallback(async (key?: string, limit: number = 50) => {
    try {
      const data = await apiFetch<{ history: ConfigChangeHistory[] }>(
        key
          ? `/api/v1/config/history?key=${key}&limit=${limit}`
          : `/api/v1/config/history?limit=${limit}`,
      );
      return data.history as ConfigChangeHistory[];
    } catch (error) {
      console.error('获取配置历史失败:', error);
      return [];
    }
  }, []);

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
      zone_draw_saved_line_width: { min: 0.1, max: 20 },
      zone_draw_active_line_width: { min: 0.1, max: 20 },
      zone_draw_point_radius: { min: 1, max: 20 },
      zone_draw_dash_on: { min: 1, max: 50 },
      zone_draw_dash_off: { min: 0, max: 50 },
      zone_draw_toolbar_bottom_px: { min: 0, max: 500 },
      zone_draw_canvas_z_index: { min: -1000, max: 1000 },
      zone_draw_toolbar_z_index: { min: -1000, max: 1000 },
      zone_yellow_h_low: { min: 0, max: 180 },
      zone_yellow_h_high: { min: 0, max: 180 },
      zone_yellow_s_low: { min: 0, max: 255 },
      zone_yellow_s_high: { min: 0, max: 255 },
      zone_yellow_v_low: { min: 0, max: 255 },
      zone_yellow_v_high: { min: 0, max: 255 },
      zone_border_v_threshold: { min: 0, max: 255 },
      zone_border_expand_px: { min: 1, max: 30 },
      zone_min_area_px: { min: 1, max: 1000000 },
      zone_max_area_ratio: { min: 0.01, max: 1.0 },
      zone_min_aspect: { min: 1.0, max: 50.0 },
      zone_max_aspect: { min: 1.0, max: 50.0 },
      zone_min_solidity: { min: 0.0, max: 1.0 },
      zone_roi_top_ratio: { min: 0.0, max: 1.0 },
      zone_morph_kernel_size: { min: 1, max: 51 },
      zone_w_area: { min: 0.0, max: 1.0 },
      zone_w_solid: { min: 0.0, max: 1.0 },
      zone_w_border: { min: 0.0, max: 1.0 },
      zone_center_crop_ratio: { min: 0.1, max: 1.0 },
      zone_center_black_v_threshold: { min: 0, max: 255 },
      zone_center_black_min_ratio: { min: 0.0, max: 1.0 },
      zone_center_text_bonus: { min: 0.0, max: 5.0 },
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
function convertValue(value: string | number | boolean, valueType: 'int' | 'float' | 'bool' | 'string'): string | number | boolean {
  const normalized = typeof value === 'string' ? value : String(value);
  switch (valueType) {
    case 'int':
      return parseInt(normalized, 10);
    case 'float':
      return parseFloat(normalized);
    case 'bool':
      if (typeof value === 'boolean') return value;
      return normalized === 'true' || normalized === '1';
    case 'string':
    default:
      return normalized;
  }
}
