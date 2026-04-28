import { useCallback, useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import { getApiUrl } from '../config/api';
import type { EvidenceItem } from '../types/evidence';

export interface UseEvidenceState {
  evidenceItems: EvidenceItem[];
  evidenceLoading: boolean;
  evidenceError: string | null;
  selectedEvidence: Set<number>;
  evidenceDeleting: boolean;
  lightboxItem: EvidenceItem | null;
  setLightboxItem: Dispatch<SetStateAction<EvidenceItem | null>>;
  searchQuery: string;
  setSearchQuery: Dispatch<SetStateAction<string>>;
  fetchEvidence: () => Promise<void>;
  deleteEvidenceByIds: (ids: number[]) => Promise<void>;
  deleteEvidenceSingle: (id: number) => void;
  deleteEvidenceSelected: () => void;
  toggleEvidenceSelected: (id: number) => void;
  toggleAllEvidence: () => void;
  filteredEvidence: EvidenceItem[];
}

export function useEvidence(): UseEvidenceState {
  const [searchQuery, setSearchQuery] = useState('');
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<Set<number>>(new Set());
  const [evidenceDeleting, setEvidenceDeleting] = useState(false);
  const [lightboxItem, setLightboxItem] = useState<EvidenceItem | null>(null);

  const fetchEvidence = useCallback(async () => {
    setEvidenceLoading(true);
    setEvidenceError(null);
    try {
      const res = await fetch(getApiUrl('/api/v1/evidence'));
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      setEvidenceItems(data.items || []);
      setSelectedEvidence(new Set());
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setEvidenceLoading(false);
    }
  }, []);

  const deleteEvidenceByIds = useCallback(async (ids: number[]) => {
    if (ids.length === 0) return;
    setEvidenceDeleting(true);
    setEvidenceError(null);
    try {
      const res = await fetch(getApiUrl('/api/v1/evidence/bulk-delete'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ evidence_ids: ids }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data.success) {
        throw new Error('删除失败');
      }
      await fetchEvidence();
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : '删除失败');
    } finally {
      setEvidenceDeleting(false);
    }
  }, [fetchEvidence]);

  const deleteEvidenceSingle = useCallback((id: number) => {
    void deleteEvidenceByIds([id]);
  }, [deleteEvidenceByIds]);

  const deleteEvidenceSelected = useCallback(() => {
    void deleteEvidenceByIds(Array.from(selectedEvidence));
  }, [deleteEvidenceByIds, selectedEvidence]);

  const toggleEvidenceSelected = useCallback((id: number) => {
    setSelectedEvidence((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const filteredEvidence = useMemo(() => {
    if (!searchQuery) return evidenceItems;
    return evidenceItems.filter((item) => (
      (item.message || '').includes(searchQuery) ||
      item.severity.includes(searchQuery)
    ));
  }, [evidenceItems, searchQuery]);

  const toggleAllEvidence = useCallback(() => {
    if (filteredEvidence.length === 0) return;
    const allSelected = filteredEvidence.every((item) => selectedEvidence.has(item.evidence_id));
    if (allSelected) {
      setSelectedEvidence(new Set());
      return;
    }
    const next = new Set<number>();
    filteredEvidence.forEach((item) => next.add(item.evidence_id));
    setSelectedEvidence(next);
  }, [filteredEvidence, selectedEvidence]);

  return {
    evidenceItems,
    evidenceLoading,
    evidenceError,
    selectedEvidence,
    evidenceDeleting,
    lightboxItem,
    setLightboxItem,
    searchQuery,
    setSearchQuery,
    fetchEvidence,
    deleteEvidenceByIds,
    deleteEvidenceSingle,
    deleteEvidenceSelected,
    toggleEvidenceSelected,
    toggleAllEvidence,
    filteredEvidence,
  };
}
