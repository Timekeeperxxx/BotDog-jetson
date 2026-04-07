/**
 * 后台管理相关的类型定义
 */

/**
 * 视频源类型
 */
export type VideoSourceType = 'whep' | 'rtsp' | 'usb';

/**
 * 网口用途
 */
export type InterfacePurpose = 'robot' | 'camera' | 'other';

/**
 * 视频源配置
 */
export interface VideoSource {
  source_id: number;
  name: string;
  label: string;
  source_type: VideoSourceType;
  whep_url: string | null;
  rtsp_url: string | null;
  enabled: boolean;
  is_primary: boolean;
  is_ai_source: boolean;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

/**
 * 视频源创建/更新请求
 */
export interface VideoSourceRequest {
  name: string;
  label: string;
  source_type: VideoSourceType;
  whep_url?: string | null;
  rtsp_url?: string | null;
  enabled: boolean;
  is_primary: boolean;
  is_ai_source: boolean;
  sort_order: number;
}

/**
 * 网口配置
 */
export interface NetworkInterface {
  iface_id: number;
  name: string;
  label: string;
  iface_name: string;
  ip_address: string | null;
  purpose: InterfacePurpose;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

/**
 * 网口创建/更新请求
 */
export interface NetworkInterfaceRequest {
  name: string;
  label: string;
  iface_name: string;
  ip_address?: string | null;
  purpose: InterfacePurpose;
  enabled: boolean;
}
