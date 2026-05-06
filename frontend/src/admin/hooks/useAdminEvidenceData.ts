import { useCallback, useEffect, useState } from 'react'
import { useEvidence } from '../../hooks/useEvidence'
import type { EvidenceItem } from '../../types/evidence'

export function useAdminEvidenceData() {
  const evidenceHook = useEvidence()
  const { fetchEvidence, deleteEvidenceByIds } = evidenceHook
  const [evidenceSearch, setEvidenceSearch] = useState('')

  const refreshEvidence = useCallback(() => {
    return fetchEvidence()
  }, [fetchEvidence])

  const deleteEvidenceItem = useCallback(async (item: EvidenceItem) => {
    await deleteEvidenceByIds([item.evidence_id])
  }, [deleteEvidenceByIds])

  useEffect(() => {
    void fetchEvidence()
  }, [fetchEvidence])

  return {
    evidenceHook,
    evidenceSearch,
    setEvidenceSearch,
    refreshEvidence,
    deleteEvidenceItem,
  }
}
