"""告警标签按已保存的事件代码区分，不修改原始证据记录。"""

EVIDENCE_LABELS = {
    'E_POSE_VAULTING_SUSPECTED': '翻越',
    'E_POSE_CLIMBING_SUSPECTED': '攀爬',
    'E_POSE_DAMAGE_SUSPECTED': '破坏动作',
    'E_POSE_CROUCHING': '蹲伏',
    'E_POSE_LYING': '倒地',
    'E_POSE_LOITERING': '徘徊',
    'E_AI_PERSON': '人员',
    'E_FACE_IDENTIFIED': '已识别人员',
    'E_AI_GUNS': '枪械',
    'E_AI_KNIFE': '刀具',
    'E_AI_FIRE': '火焰',
    'E_AI_CAR': '车辆',
    'E_AI_DOG': '犬类',
    'E_AI_CAT': '猫类',
    'E_THERMAL_HIGH': '高温',
    'E_FENCE_DWELL': '围栏附近停留',
    'E_FENCE_CONTACT': '接触围栏',
    'E_FENCE_CLIMBING_SUSPECTED': '攀爬围栏',
    'E_FENCE_TAMPERING_SUSPECTED': '疑似破坏围栏',
    'E_FENCE_TAMPERING_CONFIRMED': '确认破坏围栏',
    'NAV_PATH_BLOCKED': '道路受阻',
    'NAV_SENSOR_LOST': '导航数据中断',
    'NAV_BLOCK_CLEARED': '道路恢复',
    'NAV_AUTO_REGOAL': '导航重试',
    'FENCE_DETECTION_CONTROL_FAILED': '围栏控制故障',
    'E_FACE_SERVICE_UNAVAILABLE': '人脸服务故障',
    'E_AUTO_TRACK_LOCKED': '跟踪锁定抓拍',
    'E_AUTO_TRACK_STOPPED': '跟踪结束抓拍',
    'E_MANUAL_SNAPSHOT': '手动抓拍',
}

TYPE_LABELS = {
    'GUARD_MISSION_SNAPSHOT': '驱离抓拍',
    'AUTO_TRACK_SNAPSHOT': '跟踪抓拍',
    'AI_DETECTION': '目标检测',
    'IDENTITY_SNAPSHOT': '身份抓拍',
    'THERMAL_HIGH': '高温',
    'POSE_VAULTING_SUSPECTED': '翻越',
    'POSE_CLIMBING_SUSPECTED': '攀爬',
    'POSE_DAMAGE_SUSPECTED': '破坏动作',
    'POSE_CROUCHING': '蹲伏',
    'POSE_LYING': '倒地',
    'POSE_LOITERING': '徘徊',
}


def evidence_label(event_code: str | None, event_type: str) -> str:
    return EVIDENCE_LABELS.get(event_code or '') or TYPE_LABELS.get(event_type, '其他告警')
