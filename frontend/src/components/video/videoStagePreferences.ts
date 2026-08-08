export const AI_OVERLAY_STORAGE_KEY = 'botdog.show-ai-overlay.v2';
export const AI_OVERLAY_LAYERS_STORAGE_KEY = 'botdog.ai-overlay-layers.v3';

export type AiOverlayVisibility = {
  helmet: boolean;
  weapon: boolean;
  pose: boolean;
  face: boolean;
  tracking: boolean;
};

export type AiOverlayLayer = keyof AiOverlayVisibility;

export const DEFAULT_AI_OVERLAY_VISIBILITY: AiOverlayVisibility = {
  helmet: true,
  weapon: true,
  pose: true,
  face: true,
  tracking: true,
};

const AI_OVERLAY_LAYERS: AiOverlayLayer[] = [
  'helmet',
  'weapon',
  'pose',
  'face',
  'tracking',
];

function allLayers(visible: boolean): AiOverlayVisibility {
  return {
    helmet: visible,
    weapon: visible,
    pose: visible,
    face: visible,
    tracking: visible,
  };
}

export function getInitialAiOverlayVisibility(
  storage: Pick<Storage, 'getItem'> | null,
): AiOverlayVisibility {
  if (!storage) return { ...DEFAULT_AI_OVERLAY_VISIBILITY };

  const savedLayers = storage.getItem(AI_OVERLAY_LAYERS_STORAGE_KEY);
  if (savedLayers !== null) {
    try {
      const parsed = JSON.parse(savedLayers) as Record<string, unknown>;
      return AI_OVERLAY_LAYERS.reduce<AiOverlayVisibility>(
        (visibility, layer) => ({
          ...visibility,
          [layer]: typeof parsed[layer] === 'boolean'
            ? parsed[layer]
            : DEFAULT_AI_OVERLAY_VISIBILITY[layer],
        }),
        { ...DEFAULT_AI_OVERLAY_VISIBILITY },
      );
    } catch {
      // 损坏的本地设置回退到默认值，不影响视频画面。
    }
  }

  // 兼容旧版单一“显示/隐藏全部”设置。
  const legacyValue = storage.getItem(AI_OVERLAY_STORAGE_KEY);
  return legacyValue === 'false' ? allLayers(false) : allLayers(true);
}

export function hasVisibleAiOverlayLayer(visibility: AiOverlayVisibility): boolean {
  return AI_OVERLAY_LAYERS.some((layer) => visibility[layer]);
}
