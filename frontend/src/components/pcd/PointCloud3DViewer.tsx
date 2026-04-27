import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { NavWaypoint } from '../../types/pcdMap'
import type { RobotPose } from '../../types/navState'
import { mapToThree } from '../../utils/pointCloudTransform'

type Props = {
  points: [number, number, number][]
  waypoints: NavWaypoint[]
  robotPose: RobotPose | null
}

export function PointCloud3DViewer({ points, waypoints, robotPose }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null)
  const controlsRef = useRef<OrbitControls | null>(null)
  const cloudRef = useRef<THREE.Points | null>(null)
  const waypointGroupRef = useRef<THREE.Group | null>(null)
  const robotGroupRef = useRef<THREE.Group | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x071013)
    sceneRef.current = scene

    const camera = new THREE.PerspectiveCamera(55, 1, 0.01, 10000)
    camera.position.set(8, 8, 8)
    camera.lookAt(0, 0, 0)
    cameraRef.current = camera

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    host.appendChild(renderer.domElement)
    rendererRef.current = renderer

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08
    controlsRef.current = controls

    const grid = new THREE.GridHelper(20, 20, 0x33515a, 0x1d333a)
    scene.add(grid)
    scene.add(new THREE.AmbientLight(0xffffff, 0.85))

    const waypointGroup = new THREE.Group()
    waypointGroupRef.current = waypointGroup
    scene.add(waypointGroup)

    const robotGroup = new THREE.Group()
    robotGroup.visible = false
    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(0.18, 0.18, 0.18, 18),
      new THREE.MeshBasicMaterial({ color: 0x38bdf8 }),
    )
    body.position.y = 0.09
    robotGroup.add(body)

    const direction = new THREE.ArrowHelper(
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(0, 0.18, 0),
      0.62,
      0xf97316,
      0.22,
      0.12,
    )
    robotGroup.add(direction)
    robotGroupRef.current = robotGroup
    scene.add(robotGroup)

    const resize = () => {
      const rect = host.getBoundingClientRect()
      const width = Math.max(1, rect.width)
      const height = Math.max(1, rect.height)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
      renderer.setSize(width, height, false)
    }

    const resizeObserver = new ResizeObserver(resize)
    resizeObserver.observe(host)
    resize()

    let animationId = 0
    const animate = () => {
      controls.update()
      renderer.render(scene, camera)
      animationId = requestAnimationFrame(animate)
    }
    animate()

    return () => {
      cancelAnimationFrame(animationId)
      resizeObserver.disconnect()
      controls.dispose()
      cloudRef.current?.geometry.dispose()
      const material = cloudRef.current?.material
      if (Array.isArray(material)) material.forEach((item) => item.dispose())
      else material?.dispose()
      waypointGroup.children.forEach((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose()
          const childMaterial = child.material
          if (Array.isArray(childMaterial)) childMaterial.forEach((item) => item.dispose())
          else childMaterial.dispose()
        }
      })
      robotGroup.children.forEach((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose()
          const childMaterial = child.material
          if (Array.isArray(childMaterial)) childMaterial.forEach((item) => item.dispose())
          else childMaterial.dispose()
        } else if (child instanceof THREE.ArrowHelper) {
          child.line.geometry.dispose()
          child.cone.geometry.dispose()
          const lineMaterial = child.line.material
          if (Array.isArray(lineMaterial)) lineMaterial.forEach((item) => item.dispose())
          else lineMaterial.dispose()
          const coneMaterial = child.cone.material
          if (Array.isArray(coneMaterial)) coneMaterial.forEach((item) => item.dispose())
          else coneMaterial.dispose()
        }
      })
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [])

  useEffect(() => {
    const scene = sceneRef.current
    const camera = cameraRef.current
    const controls = controlsRef.current
    if (!scene || !camera || !controls) return

    if (cloudRef.current) {
      scene.remove(cloudRef.current)
      cloudRef.current.geometry.dispose()
      const material = cloudRef.current.material
      if (Array.isArray(material)) material.forEach((item) => item.dispose())
      else material.dispose()
      cloudRef.current = null
    }

    if (points.length === 0) return

    const positions = new Float32Array(points.length * 3)
    points.forEach(([x, y, z], index) => {
      const converted = mapToThree(x, y, z)
      positions[index * 3] = converted.x
      positions[index * 3 + 1] = converted.y
      positions[index * 3 + 2] = converted.z
    })

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.computeBoundingSphere()

    const material = new THREE.PointsMaterial({
      color: 0x5eead4,
      size: 0.035,
      sizeAttenuation: true,
    })

    const cloud = new THREE.Points(geometry, material)
    cloudRef.current = cloud
    scene.add(cloud)

    const sphere = geometry.boundingSphere
    if (sphere) {
      controls.target.copy(sphere.center)
      const radius = Math.max(2, sphere.radius)
      camera.position.set(sphere.center.x + radius, sphere.center.y + radius * 0.8, sphere.center.z + radius)
      camera.near = Math.max(0.01, radius / 1000)
      camera.far = Math.max(1000, radius * 10)
      camera.updateProjectionMatrix()
      controls.update()
    }
  }, [points])

  useEffect(() => {
    const group = waypointGroupRef.current
    if (!group) return

    group.children.forEach((child) => {
      if (child instanceof THREE.Mesh) {
        child.geometry.dispose()
        const material = child.material
        if (Array.isArray(material)) material.forEach((item) => item.dispose())
        else material.dispose()
      }
    })
    group.clear()

    const geometry = new THREE.SphereGeometry(0.16, 16, 12)
    waypoints.forEach((waypoint) => {
      const pos = mapToThree(waypoint.x, waypoint.y, waypoint.z)
      const material = new THREE.MeshBasicMaterial({ color: 0xfbbf24 })
      const sphere = new THREE.Mesh(geometry.clone(), material)
      sphere.position.set(pos.x, pos.y + 0.12, pos.z)
      group.add(sphere)
    })

    return () => {
      geometry.dispose()
    }
  }, [waypoints])

  useEffect(() => {
    const robotGroup = robotGroupRef.current
    if (!robotGroup) return

    if (!robotPose) {
      robotGroup.visible = false
      return
    }

    const pos = mapToThree(robotPose.x, robotPose.y, robotPose.z)
    robotGroup.visible = true
    robotGroup.position.set(pos.x, pos.y, pos.z)
    robotGroup.rotation.y = robotPose.yaw
  }, [robotPose])

  return (
    <div className="pcd-viewer-shell">
      <div className="pcd-viewer-label">3D 点云</div>
      <div className="pcd-three-host" ref={hostRef} />
      {points.length === 0 ? <div className="pcd-viewer-empty">等待点云预览数据</div> : null}
    </div>
  )
}
