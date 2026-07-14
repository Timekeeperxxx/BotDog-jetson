import type { RobotCommand } from '../hooks/useRobotControl'

export function resolveRobotCommandFromKey(key: string): RobotCommand | null {
  switch (key.toLowerCase()) {
    case 'w':
      return 'forward'
    case 's':
      return 'backward'
    case 'a':
      return 'strafe_left'
    case 'd':
      return 'strafe_right'
    case 'q':
      return 'left'
    case 'e':
      return 'right'
    case 'control':
      return 'sit'
    case 'shift':
      return 'stand'
    default:
      return null
  }
}
