export const AI_OVERLAY_STORAGE_KEY = 'botdog.show-ai-overlay.v2';

export function getInitialAiOverlayVisibility(
  storage: Pick<Storage, 'getItem'> | null,
): boolean {
  if (!storage) return true;
  const savedValue = storage.getItem(AI_OVERLAY_STORAGE_KEY);
  return savedValue === null ? true : savedValue === 'true';
}
