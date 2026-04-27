export function mapToThree(x: number, y: number, z: number) {
  return {
    x,
    y: z,
    z: -y,
  }
}

export function threeToMap(x: number, y: number, z: number) {
  return {
    x,
    y: -z,
    z: y,
  }
}
