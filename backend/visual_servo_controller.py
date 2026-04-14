"""
视觉伺服控制器（驱离闭环专用）。

职责边界：
- 接收视觉底层输出的安全框/锚点坐标。
- 生成对应的机器狗遥控指令（速度控制、方向微调）。
- 不触碰任何硬件和 IO 操作，仅作为策略计算模型。
"""

import time
from typing import Tuple, Optional

class VisualServoController:
    def __init__(self, yaw_deadband_px: int = 40):
        self._yaw_deadband_px = yaw_deadband_px

    def compute_advancing(self, curr_bbox: Tuple[int, int, int, int], frame_width: int, frame_height: int, max_view_ratio: float) -> Tuple[str, bool]:
        """
        计算前进阶段（ADVANCING）的策略。
        :param curr_bbox: 锚点 (x, y, w, h)
        :param frame_width: 画面全宽
        :param frame_height: 画面全高
        :param max_view_ratio: 最大面积保护率 比如 0.90，一旦锚点面积占据了 90% 的边界，代表走到底了
        :return: (需要发送的动作指令, 是否到达了终点极限应该踩刹车了)
        """
        x, y, w, h = curr_bbox
        center_x = x + w // 2
        
        # 判断转向
        # 计算偏离中心的距离
        error_x = center_x - (frame_width // 2)
        cmd = "forward"
        
        if abs(error_x) > self._yaw_deadband_px:
            if error_x < 0:
                # 锚点在左边偏出死区，我们往左微调
                cmd = "left"
            else:
                # 锚点在右边，往右纠正机头
                cmd = "right"
                
        # 判定是否把大门（防区）完整塞满整个屏幕了
        # 宽或者高任意一边触达画面边界的阈值即判定为贴近终点
        if w >= frame_width * max_view_ratio or h >= frame_height * max_view_ratio:
            is_arrived_edge = True
            cmd = "stop"  # 即使没转正，也停止一切动作
        else:
            is_arrived_edge = False
            
        return cmd, is_arrived_edge

    def compute_returning(self, 
                          curr_bbox: Tuple[int, int, int, int],
                          start_bbox: Tuple[int, int, int, int], 
                          frame_width: int, 
                          pos_tolerance_px: int, 
                          area_tolerance_ratio: float) -> Tuple[str, bool]:
        """
        计算闭环返航阶段（RETURNING）的策略。
        :param curr_bbox: (x, y, w, h) 当前锚点
        :param start_bbox: (x, y, w, h) 起跑时的初始锚点（目标）
        :param frame_width: 画面宽，用于中心点校验
        :param pos_tolerance_px: 能容忍退回到初始X坐标多少像素内的误差
        :param area_tolerance_ratio: 面积恢复到原始尺度的允许偏差（比如 0.1 代表回到原始的 +/- 10% 即认为回到了原位）
        :return: (对应需要指令, 是否已经安全回位完美贴合原始锚点)
        """
        curr_x, curr_y, curr_w, curr_h = curr_bbox
        start_x, start_y, start_w, start_h = start_bbox
        
        curr_center_x = curr_x + curr_w // 2
        start_center_x = start_x + start_w // 2
        
        # 在退回的过程中，机头始终是对着前方大门（锚点）的
        # 为了保证它不是“斜着倒车退走”的，一旦它发现目标在屏幕偏左了，就原地往左扭一点转回来
        error_x = curr_center_x - (frame_width // 2)
        cmd = "backward"
        
        if abs(error_x) > self._yaw_deadband_px:
            if error_x < 0:
                cmd = "left"
            else:
                cmd = "right"

        # 判断是否到达
        # 评判标准 1: 面积缩小到了起步时的设定值 (代表后退了一段物理距离)
        curr_area = curr_w * curr_h
        start_area = start_w * start_h
        
        # 理论上只要它持续倒退，面积就会持续减小。当当前面积 <= 理论设定的面积上限即可
        # 即它回到了差不多的物理深度
        area_upper_bound = start_area * (1.0 + area_tolerance_ratio)
        has_reached_z = (curr_area <= area_upper_bound)
        
        # 评判标准 2：位置归中 (X 方向中心点和起跑时差不多重合)
        has_reached_x = (abs(curr_center_x - start_center_x) <= pos_tolerance_px)
        
        if has_reached_z and has_reached_x:
            is_returned = True
            cmd = "stop"
        else:
            is_returned = False
            
        return cmd, is_returned
