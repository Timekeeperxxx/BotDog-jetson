import { describe, expect, it } from 'vitest'
import { validateWaypointName } from './navWaypointValidation'

describe('validateWaypointName', () => {
  it('rejects blank names', () => {
    expect(validateWaypointName('   ', [])).toEqual({
      ok: false,
      message: '请输入导航点名称',
    })
  })

  it('rejects duplicate waypoint names after trimming', () => {
    expect(validateWaypointName('  巡检点1  ', ['巡检点1', '巡检点2'])).toEqual({
      ok: false,
      message: '导航点名称不能重复',
    })
  })

  it('accepts unique waypoint names', () => {
    expect(validateWaypointName('巡检点3', ['巡检点1', '巡检点2'])).toEqual({
      ok: true,
      value: '巡检点3',
    })
  })
})
