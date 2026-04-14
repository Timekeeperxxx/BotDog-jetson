"""
视觉锚点跟踪模块。

职责边界：
- 封装 OpenCV TrackerMIL 进行背景特征/目标区域锁定。
- 处理二进制 BGR24 视频流到 numpy 的转化。
- 提供帧级别的坐标更新与追踪丢失反馈。
"""

import logging
from typing import Tuple, Optional

import numpy as np

logger = logging.getLogger("botdog.visual_tracker")


class VisualAnchorTracker:
    def __init__(self):
        self._tracker = None
        self._is_initialized = False
        
        # 为了捕获如果运行环境里没有 opencv-contrib 或者特殊版本的退路
        self._tracker_type = "MIL"

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    def init_anchor(self, frame_bytes: bytes, frame_width: int, frame_height: int, bbox: Tuple[int, int, int, int]) -> bool:
        """
        初始化追踪器，在触发瞬间调用。
        :param frame_bytes: BGR24 的原始字节数组
        :param frame_width: 画面宽
        :param frame_height: 画面高
        :param bbox: (x_min, y_min, width, height) 格式
        :return: bool 是否成功
        """
        try:
            import cv2
            
            # 使用经典的 MIL 算法，大部分 Python-OpenCV 自带，无强依赖
            self._tracker = cv2.TrackerMIL_create()
            
            # 转换 frame_bytes 到 OpenCV 需要的格式
            frame_np = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((frame_height, frame_width, 3))
            
            # opencv tracker 需要的是 (x, y, w, h)，和我们的输入一致
            ok = self._tracker.init(frame_np, bbox)
            self._is_initialized = ok
            if ok:
                logger.info(f"[VisualAnchorTracker] 锚点初始化成功: {bbox}")
            else:
                logger.error("[VisualAnchorTracker] 锚点跟踪器初始化失败")
            return ok
            
        except ImportError:
            logger.error("[VisualAnchorTracker] 无法导入 cv2，请确认已安装 opencv-python")
            self._is_initialized = False
            return False
        except Exception as e:
            logger.exception(f"[VisualAnchorTracker] 初始化异常: {e}")
            self._is_initialized = False
            return False

    def update_anchor(self, frame_bytes: bytes, frame_width: int, frame_height: int) -> Tuple[bool, Optional[Tuple[int, int, int, int]]]:
        """
        更新跟踪状态，每一帧调用。
        :return: (ok, bbox(x, y, w, h))
        """
        if not self._is_initialized or self._tracker is None:
            return False, None
            
        try:
            frame_np = np.frombuffer(frame_bytes, dtype=np.uint8).reshape((frame_height, frame_width, 3))
            ok, bbox = self._tracker.update(frame_np)
            
            if ok:
                # opencv 返回的可能是 float 的 tuple，转为 int 以防万一
                x, y, w, h = [int(v) for v in bbox]
                return True, (x, y, w, h)
            else:
                return False, None
                
        except Exception as e:
            # 避免局部异常导致整条链路挂掉
            logger.debug(f"[VisualAnchorTracker] 更新特征帧异常 {e}")
            return False, None

    def reset(self):
        """完全重置内部状态，以便下一轮任务使用"""
        self._tracker = None
        self._is_initialized = False
