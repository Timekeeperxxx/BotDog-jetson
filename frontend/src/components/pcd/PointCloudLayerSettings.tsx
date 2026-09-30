import { NO_HEIGHT_CLIP, type HeightClip } from './PointCloudHeightClip'
import type { WallColorMode } from '../../types/pcdMap'

type Props = {
  pcdLayerVisibility: { map: boolean; ground: boolean; footprint: boolean }
  onToggleLayer: (layer: 'map' | 'ground' | 'footprint') => void
  wallColorMode: WallColorMode
  onSelectWallColorMode: (mode: WallColorMode) => void
  heightClip?: HeightClip
  onHeightClip?: (value: HeightClip) => void
  pointSize?: number
  onPointSize?: (value: number) => void
  intensityPreference?: number
  onIntensityPreference?: (value: number) => void
}

// Both navigation and simulation use these controls and the same viewer props.
export function PointCloudLayerSettings({ pcdLayerVisibility, onToggleLayer,
  wallColorMode, onSelectWallColorMode, heightClip = NO_HEIGHT_CLIP, onHeightClip,
  pointSize = 1, onPointSize, intensityPreference = 0, onIntensityPreference }: Props) {
  return <>
              <button
                type="button"
                className={`pcd-layer-toggle ${pcdLayerVisibility.map ? 'is-active' : ''}`}
                onClick={() => onToggleLayer('map')}
              >
                <span className="pcd-layer-swatch is-map" />
                <span>墙壁 / 场景</span>
              </button>
              <button
                type="button"
                className={`pcd-layer-toggle ${pcdLayerVisibility.ground ? 'is-active' : ''}`}
                onClick={() => onToggleLayer('ground')}
              >
                <span className="pcd-layer-swatch is-ground" />
                <span>地面</span>
              </button>
              <button
                type="button"
                className={`pcd-layer-toggle ${pcdLayerVisibility.footprint ? 'is-active' : ''}`}
                onClick={() => onToggleLayer('footprint')}
              >
                <span className="pcd-layer-swatch is-footprint" />
                <span>足迹填充</span>
              </button>
              <div className="pcd-layer-setting-group">
                <span>墙壁颜色</span>
                <div className="pcd-layer-segments" role="group" aria-label="wall 点云显示颜色">
                  {([
                    ['intensity', '强度'],
                    ['height', '高度'],
                  ] as const).map(([mode, label]) => (
                    <button
                      key={mode}
                      type="button"
                      className={wallColorMode === mode ? 'is-active' : ''}
                      onClick={() => onSelectWallColorMode(mode)}
                      aria-pressed={wallColorMode === mode}
                    >
                      <i className={`pcd-layer-swatch is-wall-color is-${mode}`} />
                      {label}
                    </button>
                  ))}
                </div>
              </div>
              {wallColorMode === 'intensity' && (
                <div className="pcd-layer-setting-group pcd-color-preference">
                  <label htmlFor="pcd-color-preference">色彩偏好</label>
                  <input id="pcd-color-preference" type="range" min={-100} max={100} step={1}
                    value={Math.round(intensityPreference * 100)}
                    aria-valuetext={intensityPreference === 0 ? '均衡' : `${intensityPreference < 0 ? '偏蓝' : '偏红'} ${Math.abs(Math.round(intensityPreference * 100))}%`}
                    onChange={event => onIntensityPreference?.(Number(event.target.value) / 100)} />
                  <div className="pcd-color-preference-labels"><span>偏蓝</span><button type="button" onClick={() => onIntensityPreference?.(0)}>均衡</button><span>偏红</span></div>
                </div>
              )}
              <div className="pcd-layer-setting-group pcd-color-preference">
                <label htmlFor="pcd-point-size">单点大小 <output>{pointSize.toFixed(1)}×</output></label>
                <input id="pcd-point-size" type="range" min={0.1} max={3} step={0.1}
                  value={pointSize} aria-valuetext={`${pointSize.toFixed(1)} 倍`}
                  onChange={event => onPointSize?.(Number(event.target.value))} />
                <div className="pcd-color-preference-labels"><span>小</span><button type="button" onClick={() => onPointSize?.(1)}>默认大小</button><span>大</span></div>
              </div>
              <div className="pcd-layer-setting-group pcd-height-clip">
                <span>高度裁切（米）</span>
                <label>最低高度<input type="number" step="0.1" placeholder="不限" value={heightClip.min ?? ''}
                  onChange={e => { const value = e.target.value === '' ? null : e.target.valueAsNumber; if (value === null || Number.isFinite(value)) onHeightClip?.({ ...heightClip, min: value === null ? null : Math.min(value, heightClip.max ?? Infinity) }) }} /></label>
                <label>最高高度<input type="number" step="0.1" placeholder="不限" value={heightClip.max ?? ''}
                  onChange={e => { const value = e.target.value === '' ? null : e.target.valueAsNumber; if (value === null || Number.isFinite(value)) onHeightClip?.({ ...heightClip, max: value === null ? null : Math.max(value, heightClip.min ?? -Infinity) }) }} /></label>
                <small>按地图坐标高度裁切，留空表示不限。</small>
                <button type="button" onClick={() => onHeightClip?.(NO_HEIGHT_CLIP)}>取消裁切</button>
              </div>
              <div className="pcd-layer-setting-group">
                <span>点云</span>
                <div className="pcd-layer-segments" role="group" aria-label="点云显示模式">
                  <span className="is-active">原始</span>
                </div>
                <small>静止时逐步补齐原始点云；跟随时持续加载。</small>
              </div>
  </>
}
