import * as THREE from 'three'

export type CloudMotion = 'stationary' | 'manual' | 'following'

/** Admission controls work per frame, never retained memory or total point count. */
export function cloudLoadConcurrency(mode: CloudMotion, frameMs: number, workMs = 0) {
  if (mode === 'stationary') return frameMs > 45 ? 2 : 6
  if (frameMs > 35 || workMs > 16) return 1
  return mode === 'following' ? 5 : 4
}

export function predictCameraPosition(position: THREE.Vector3, velocity: THREE.Vector3) {
  // Predict only a short corridor; a jump in localization must not prefetch miles.
  return position.clone().add(velocity.clone().clampLength(0, 4).multiplyScalar(0.8))
}

export class PotreeMotionTracker {
  private previous = new THREE.Vector3()
  private rotation = new THREE.Quaternion()
  private lastAt = 0
  private lastMovement = -Infinity
  readonly velocity = new THREE.Vector3()

  update(camera: THREE.Camera, interacting: boolean, following: boolean, now: number): CloudMotion {
    const elapsed = this.lastAt ? (now - this.lastAt) / 1000 : 0
    const moved = this.lastAt > 0 && (camera.position.distanceToSquared(this.previous) > 1e-10
      || 1 - Math.abs(camera.quaternion.dot(this.rotation)) > 1e-10)
    if (moved || interacting) this.lastMovement = now
    if (elapsed > 0 && elapsed < 1 && moved) {
      const next = camera.position.clone().sub(this.previous).divideScalar(elapsed)
      this.velocity.lerp(next, 0.25)
    } else this.velocity.multiplyScalar(0.9)
    this.previous.copy(camera.position)
    this.rotation.copy(camera.quaternion)
    this.lastAt = now
    if (interacting) return 'manual'
    if (now - this.lastMovement < 120) return following ? 'following' : 'manual'
    return 'stationary'
  }
}
