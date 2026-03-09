/**
 * API 配置工具。
 *
 * 从环境变量读取后端地址，统一管理所有 API 和 WebSocket 连接。
 */

// 后端地址配置
// Windows 宿主机原生运行环境，后端在本地
const API_BASE_URL = 'http://192.168.144.30:8000';

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
