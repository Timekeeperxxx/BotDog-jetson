import { useCallback, useState } from 'react';
import { getApiUrl } from '../config/api';

export interface RecordingItem {
  recording_id: number;
  camera_name: string;
  video_url: string;
  file_size_bytes: number | null;
  duration_seconds: number | null;
  task_id: number | null;
  started_at: string;
  ended_at: string | null;
}

export interface UseRecordingsState {
  recordings: RecordingItem[];
  loading: boolean;
  error: string | null;
  fetchRecordings: () => Promise<void>;
}

export function useRecordings(): UseRecordingsState {
  const [recordings, setRecordings] = useState<RecordingItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchRecordings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(getApiUrl('/api/v1/recordings'));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRecordings(data.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  return { recordings, loading, error, fetchRecordings };
}
