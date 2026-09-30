import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { cloudLoadConcurrency, PotreeMotionTracker, predictCameraPosition } from './PotreeMotion'

describe('original point cloud motion scheduling', () => {
  it('continues admitting detail throughout continuous robot following', () => {
    const tracker = new PotreeMotionTracker()
    const camera = new THREE.PerspectiveCamera()
    tracker.update(camera, false, true, 1)
    for (let i = 1; i <= 600; i++) {
      camera.position.x = i * 0.02
      const mode = tracker.update(camera, false, true, i * 50)
      expect(mode).toBe('following')
      expect(cloudLoadConcurrency(mode, 16)).toBe(5)
    }
    expect(tracker.update(camera, false, true, 30200)).toBe('stationary')
    expect(cloudLoadConcurrency('stationary', 16)).toBeGreaterThan(cloudLoadConcurrency('following', 16))
  })
  it('distinguishes manual orbit from robot tracking and handles localization jumps', () => {
    const tracker = new PotreeMotionTracker()
    const camera = new THREE.PerspectiveCamera()
    expect(tracker.update(camera, true, true, 1)).toBe('manual')
    const prediction = predictCameraPosition(new THREE.Vector3(), new THREE.Vector3(1000, 0, 0))
    expect(prediction.length()).toBeCloseTo(3.2)
    expect(cloudLoadConcurrency('manual', 16)).toBe(4)
    expect(cloudLoadConcurrency('following', 16, 20)).toBe(1)
    expect(cloudLoadConcurrency('following', 60)).toBe(1)
  })
})
