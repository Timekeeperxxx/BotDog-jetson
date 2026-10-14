export type EvidenceSeverity = 'INFO' | 'WARNING' | 'CRITICAL';

export interface EvidenceItem {
  alert_label?: string | null;
  evidence_id: number;
  task_id: number | null;
  event_type: string;
  event_code?: string | null;
  severity: EvidenceSeverity;
  message?: string | null;
  confidence?: number | null;
  file_path: string | null;
  image_url?: string | null;
  gps_lat?: number | null;
  gps_lon?: number | null;
  created_at: string;
}

export interface EvidenceLabel {
  value: string;
  label: string;
  count: number;
}
