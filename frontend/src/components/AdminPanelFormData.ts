import type { NetworkInterface, VideoSource } from '../types/admin';

export interface VideoFormData {
  name: string;
  label: string;
  source_type: string;
  whep_url: string;
  rtsp_url: string;
  enabled: boolean;
  is_primary: boolean;
  is_ai_source: boolean;
  sort_order: number;
}

export function emptyVideoForm(): VideoFormData {
  return {
    name: '', label: '', source_type: 'whep',
    whep_url: '', rtsp_url: '',
    enabled: true, is_primary: false, is_ai_source: false, sort_order: 0,
  };
}

export function sourceToForm(src: VideoSource): VideoFormData {
  return {
    name: src.name, label: src.label, source_type: src.source_type,
    whep_url: src.whep_url || '', rtsp_url: src.rtsp_url || '',
    enabled: src.enabled, is_primary: src.is_primary, is_ai_source: src.is_ai_source,
    sort_order: src.sort_order,
  };
}

export interface IfaceFormData {
  name: string;
  label: string;
  iface_name: string;
  ip_address: string;
  purpose: string;
  enabled: boolean;
}

export function emptyIfaceForm(): IfaceFormData {
  return { name: '', label: '', iface_name: '', ip_address: '', purpose: 'other', enabled: true };
}

export function ifaceToForm(iface: NetworkInterface): IfaceFormData {
  return {
    name: iface.name, label: iface.label, iface_name: iface.iface_name,
    ip_address: iface.ip_address || '', purpose: iface.purpose, enabled: iface.enabled,
  };
}
