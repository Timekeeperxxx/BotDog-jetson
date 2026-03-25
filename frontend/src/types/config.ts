/**
 * 系统配置相关的类型定义
 */

/**
 * 配置值类型
 */
export type ConfigValueType = 'int' | 'float' | 'bool' | 'string';

/**
 * 配置类别
 */
export type ConfigCategory = 'backend' | 'frontend' | 'storage' | 'auto_track';

/**
 * 系统配置项
 */
export interface SystemConfig {
  config_id: number;
  key: string;
  value: string | number | boolean;
  value_type: ConfigValueType;
  category: ConfigCategory;
  description: string;
  is_hot_reloadable: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * 配置变更历史记录
 */
export interface ConfigChangeHistory {
  history_id: number;
  config_key: string;
  old_value: string;
  new_value: string;
  changed_by: string;
  changed_at: string;
  reason: string;
}

/**
 * 配置验证规则
 */
export interface ConfigValidationRule {
  min?: number;
  max?: number;
  options?: string[]; // 对于 string/bool 类型的可选值
}

/**
 * 配置分组
 */
export interface ConfigGroup {
  name: ConfigCategory;
  displayName: string;
  configs: SystemConfig[];
}

/**
 * 配置面板状态
 */
export interface ConfigPanelState {
  configs: Record<string, SystemConfig>;
  loading: boolean;
  error: string | null;
  selectedCategory: ConfigCategory;
  showHistory: boolean;
  history: ConfigChangeHistory[];
  editingKey: string | null;
  editValue: string | number | boolean;
}
