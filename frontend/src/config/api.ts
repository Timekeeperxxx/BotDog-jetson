/**
 * API 配置工具。
 *
 * 从环境变量读取后端地址，统一管理所有 API 和 WebSocket 连接。
 */

// 后端地址配置
// 优先使用 VITE_API_BASE_URL（构建时注入）；
// 未设置时自动使用当前页面的 origin，兼容后端托管 SPA 的场景（OrangePi 无需写死 IP）。
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://192.168.123.222:8000";

/**
 * 获取后端 API 基础 URL
 */
export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

/**
 * 将 HTTP URL 转换为 WebSocket URL
 */
export function getWsUrl(path: string): string {
  const url = new URL(API_BASE_URL);
  const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${url.host}${path}`;
  return wsUrl;
}

/**
 * 获取完整的 API URL
 */
export function getApiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}
