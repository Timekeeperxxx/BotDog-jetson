import { useCallback, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import { getApiUrl } from '../config/api';
import type { EvidenceItem } from '../types/evidence';

const EVIDENCE_PAGE_SIZE = 50;

export interface UseEvidenceState {
  evidenceItems: EvidenceItem[];
  evidenceLoading: boolean;
  evidenceLoadingMore: boolean;
  evidenceHasMore: boolean;
  evidenceLoadMoreError: string | null;
  evidenceError: string | null;
  detailLoading: boolean;
  detailError: string | null;
  selectedEvidence: Set<number>;
  evidenceDeleting: boolean;
  lightboxItem: EvidenceItem | null;
  setLightboxItem: Dispatch<SetStateAction<EvidenceItem | null>>;
  searchQuery: string;
  setSearchQuery: Dispatch<SetStateAction<string>>;
  fetchEvidence: () => Promise<void>;
  loadMoreEvidence: () => Promise<void>;
  openEvidence: (id: number) => Promise<void>;
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
  const [evidenceLoadingMore, setEvidenceLoadingMore] = useState(false);
  const [evidenceHasMore, setEvidenceHasMore] = useState(false);
  const [evidenceLoadMoreError, setEvidenceLoadMoreError] = useState<string | null>(null);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const listRequestRef = useRef(0);
  const loadingMoreRef = useRef(false);
  const [selectedEvidence, setSelectedEvidence] = useState<Set<number>>(new Set());
  const [evidenceDeleting, setEvidenceDeleting] = useState(false);
  const [lightboxItem, setLightboxItem] = useState<EvidenceItem | null>(null);

  const fetchEvidence = useCallback(async () => {
    const request = ++listRequestRef.current;
    loadingMoreRef.current = false;
    setEvidenceLoadingMore(false);
    setEvidenceLoadMoreError(null);
    setEvidenceLoading(true);
    setEvidenceError(null);
    try {
      const res = await fetch(getApiUrl(`/api/v1/evidence?offset=0&limit=${EVIDENCE_PAGE_SIZE}`));
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      if (request !== listRequestRef.current) return;
      const items: EvidenceItem[] = data.items || [];
      setEvidenceItems(items);
      setEvidenceHasMore(data.has_more ?? items.length === EVIDENCE_PAGE_SIZE);
      setSelectedEvidence((selected) => new Set(items.filter((item) => selected.has(item.evidence_id)).map((item) => item.evidence_id)));
    } catch (err) {
      if (request === listRequestRef.current) setEvidenceError(err instanceof Error ? err.message : '加载失败');
    } finally {
      if (request === listRequestRef.current) setEvidenceLoading(false);
    }
  }, []);

  const loadMoreEvidence = useCallback(async () => {
    if (!evidenceHasMore || loadingMoreRef.current) return;
    loadingMoreRef.current = true;
    setEvidenceLoadingMore(true);
    setEvidenceLoadMoreError(null);
    const offset = evidenceItems.length;
    const request = listRequestRef.current;
    try {
      const res = await fetch(getApiUrl(`/api/v1/evidence?offset=${offset}&limit=${EVIDENCE_PAGE_SIZE}`));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (request !== listRequestRef.current) return;
      const items: EvidenceItem[] = data.items || [];
      setEvidenceItems((current) => {
        const known = new Set(current.map((item) => item.evidence_id));
        return [...current, ...items.filter((item) => !known.has(item.evidence_id))];
      });
      setEvidenceHasMore(data.has_more ?? items.length === EVIDENCE_PAGE_SIZE);
    } catch (err) {
      if (request === listRequestRef.current) setEvidenceLoadMoreError(err instanceof Error ? err.message : '加载失败');
    } finally {
      loadingMoreRef.current = false;
      setEvidenceLoadingMore(false);
    }
  }, [evidenceHasMore, evidenceItems.length]);

  const openEvidence = useCallback(async (id: number) => {
    setLightboxItem(null);
    setDetailLoading(true);
    setDetailError(null);
    try {
      const res = await fetch(getApiUrl(`/api/v1/evidence/${id}`));
      if (!res.ok) throw new Error(res.status === 404 ? '告警记录不存在或已删除' : '详情加载失败，请重试');
      const item: EvidenceItem = await res.json();
      setLightboxItem(item);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : '详情加载失败');
    } finally {
      setDetailLoading(false);
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
    evidenceLoadingMore,
    evidenceHasMore,
    evidenceLoadMoreError,
    evidenceError,
    detailLoading,
    detailError,
    selectedEvidence,
    evidenceDeleting,
    lightboxItem,
    setLightboxItem,
    searchQuery,
    setSearchQuery,
    fetchEvidence,
    loadMoreEvidence,
    openEvidence,
    deleteEvidenceByIds,
    deleteEvidenceSingle,
    deleteEvidenceSelected,
    toggleEvidenceSelected,
    toggleAllEvidence,
    filteredEvidence,
  };
}
