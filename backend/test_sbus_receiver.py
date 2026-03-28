"""
SBUS遥控器接收测试脚本。

功能：
- 从COM7端口读取SBUS协议数据
- 解析SBUS数据包（16个通道+ flags）
- 实时显示通道数据
- 支持通道数据映射到标准范围（1000-2000μs）

硬件连接：
- FT24遥控器接收器 SBUS输出 -> COM7串口
- SBUS默认参数：100000波特率，8E2（8位数据位，偶校验，2停止位）

使用方法：
    python backend/test_sbus_receiver.py
"""

import serial
import struct
import asyncio
from typing import Optional, TextIO
from loguru import logger
from datetime import datetime
from pathlib import Path


class SBUSReceiver:
    """
    SBUS协议接收器。

    SBUS协议规范：
    - 波特率：100000
    - 数据位：8
    - 校验位：偶校验（Even）
    - 停止位：2
    - 数据包长度：25字节
    - 更新率：约7ms（14Hz）或更快
    """

    # SBUS数据包常量
    SBUS_FRAME_SIZE = 25
    SBUS_HEADER_BYTE = 0x0F
    SBUS_FOOTER_BYTE = 0x00
    SBUS_FOOTER2_BYTE = 0x04

    # SBUS标志位
    FLAG_CH17 = 0x01  # 第17通道（数字）
    FLAG_CH18 = 0x02  # 第18通道（数字）
    FLAG_FRAME_LOST = 0x04  # 帧丢失
    FLAG_FAILSAFE = 0x08  # 失效保护

    def __init__(self, port: str = "COM7", baudrate: int = 100000, invert: bool = True, log_path: Optional[str] = None):
        """
        初始化SBUS接收器。

        Args:
            port: 串口名称（Windows: COM7, Linux: /dev/ttyUSB0）
            baudrate: 波特率（SBUS标准为100000）
            invert: 是否进行软件反相（SBUS通常为反向电平）
        """
        self.port = port
        self.baudrate = baudrate
        self.invert = invert
        self.serial_conn: Optional[serial.Serial] = None
        self.channels = [0] * 18  # 18个通道（16个模拟 + 2个数字）
        self.flags = 0  # 标志位
        self._buffer = bytearray()
        self.log_path = log_path
        self._log_fp: Optional[TextIO] = None

    def connect(self) -> bool:
        """
        连接到串口。

        Returns:
            bool: 连接是否成功
        """
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_EVEN,
                stopbits=serial.STOPBITS_TWO,
                timeout=0.1  # 100ms超时
            )
            logger.info(f"成功连接到 {self.port} @ {self.baudrate} baud (8E2)")

            if self.log_path:
                Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
                self._log_fp = open(self.log_path, "a", encoding="utf-8")
                logger.info(f"原始数据日志输出到: {self.log_path}")
            return True
        except serial.SerialException as e:
            logger.error(f"连接串口失败: {e}")
            return False

    def disconnect(self):
        """断开串口连接。"""
        if self._log_fp:
            self._log_fp.close()
            self._log_fp = None

        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            logger.info("串口已关闭")

    def decode_sbus_data(self, data: bytes) -> tuple[list[int], int]:
        if self.invert:
            data = bytes((~b) & 0xFF for b in data)

        # 若开启反相，起始字节应变为 0x0F
        """
        解码SBUS数据包。

        SBUS数据格式（25字节）：
        [0]      : 0x0F (起始字节)
        [1-22]   : 16个通道数据（每个通道11位，共176位 = 22字节）
        [23]     : 标志位（CH17, CH18, FRAME_LOST, FAILSAFE）
        [24]     : 0x00 (结束字节)

        Args:
            data: 25字节的SBUS数据包

        Returns:
            tuple: (通道列表[18], 标志位)
        """
        if len(data) != self.SBUS_FRAME_SIZE:
            raise ValueError(f"无效的SBUS数据包长度: {len(data)}, 期望 {self.SBUS_FRAME_SIZE}")

        if data[0] != self.SBUS_HEADER_BYTE:
            raise ValueError(f"无效的SBUS起始字节: 0x{data[0]:02X}")

        # 结束字节在不同设备上可能变化，这里不做强校验

        channels = [0] * 16

        # 解析16个模拟通道（每个11位）
        # 数据位在字节[1-23]中打包
        for i in range(16):
            # 每个通道占11位，跨越字节边界
            byte_start = 1 + (i * 11 // 8)
            bit_shift = (i * 11) % 8

            # 读取11位数据
            if bit_shift <= 5:  # 不跨越3字节边界
                value = (data[byte_start] >> bit_shift) | \
                       (data[byte_start + 1] << (8 - bit_shift))
                value &= 0x7FF  # 保留低11位
            else:  # 跨越3字节边界
                value = (data[byte_start] >> bit_shift) | \
                       (data[byte_start + 1] << (8 - bit_shift)) | \
                       (data[byte_start + 2] << (16 - bit_shift))
                value &= 0x7FF

            channels[i] = value

        # 解析标志位
        flags = data[23]

        # 解析数字通道17和18
        ch17 = 1 if (flags & self.FLAG_CH17) else 0
        ch18 = 1 if (flags & self.FLAG_CH18) else 0

        channels.extend([ch17, ch18])

        return channels, flags

    def scale_channel(self, raw_value: int) -> int:
        """
        将原始通道值（0-2047）映射到标准PWM范围（1000-2000μs）。

        Args:
            raw_value: 原始通道值（0-2047）

        Returns:
            int: PWM值（1000-2000）
        """
        # SBUS范围：0-2047（11位）
        # PWM范围：1000-2000μs
        pwm_min = 1000
        pwm_max = 2000
        sbus_min = 0
        sbus_max = 2047

        scaled = pwm_min + (raw_value - sbus_min) * (pwm_max - pwm_min) // (sbus_max - sbus_min)
        return scaled

    def read_frame(self) -> Optional[tuple[list[int], int, bytes]]:
        """
        读取一个SBUS数据帧。

        Returns:
            Optional[tuple]: (通道列表, 标志位, 原始数据包) 或 None（读取失败）
        """
        if not self.serial_conn or not self.serial_conn.is_open:
            logger.error("串口未连接")
            return None


        
        try:
            # 持续累积串口数据，按0x0F对齐提取25字节帧
            chunk = self.serial_conn.read(self.serial_conn.in_waiting or 1)
            
            if chunk:
                self._buffer.extend(chunk)
            
            print(self._buffer.hex())  # 调试输出当前缓冲区内容

            while True:
                # 查找起始字节
                start_index = self._buffer.find(bytes([self.SBUS_HEADER_BYTE]))
                if start_index < 0:
                    # 未找到起始字节，清空缓冲保留最后一个字节防止跨包
                    if len(self._buffer) > 1:
                        self._buffer = self._buffer[-1:]
                    return None

                # 丢弃起始字节前的噪声
                if start_index > 0:
                    del self._buffer[:start_index]

                # 数据不足一帧，等待更多数据
                if len(self._buffer) < self.SBUS_FRAME_SIZE:
                    return None

                # 提取一帧
                frame = bytes(self._buffer[:self.SBUS_FRAME_SIZE])
                del self._buffer[:self.SBUS_FRAME_SIZE]

                # 解码数据
                channels, flags = self.decode_sbus_data(frame)
                return channels, flags, frame

        except Exception as e:
            logger.error(f"读取SBUS数据失败: {e}")

        return None

    def print_raw_frame(self, raw_frame: bytes, channels: list[int]):
        """
        打印原始SBUS数据，并按通道分组。

        Args:
            raw_frame: 原始SBUS数据包
            channels: 通道值列表
        """
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        raw_hex = " ".join(f"{b:02X}" for b in raw_frame)

        def group_line(start_ch: int, values: list[int]) -> str:
            parts = [f"CH{start_ch + i}={v}" for i, v in enumerate(values)]
            return " ".join(parts)

        line_raw = f"{ts} | RAW: {raw_hex}"
        line_ch = (
            f"{ts} | CH1-4: {group_line(1, channels[0:4])}"
            f" | CH5-8: {group_line(5, channels[4:8])}"
            f" | CH9-12: {group_line(9, channels[8:12])}"
            f" | CH13-16: {group_line(13, channels[12:16])}"
            f" | CH17-18: {group_line(17, channels[16:18])}"
        )

        print(line_raw)
        print(line_ch)
        if self._log_fp:
            self._log_fp.write(line_raw + "\n")
            self._log_fp.write(line_ch + "\n")

    async def start_reading(self, duration_seconds: Optional[int] = None):
        """
        开始读取SBUS数据。

        Args:
            duration_seconds: 运行时长（秒），None表示无限期运行
        """
        if not self.connect():
            return

        logger.info("开始读取SBUS数据...")
        if duration_seconds:
            logger.info(f"将在 {duration_seconds} 秒后自动停止")

        start_time = asyncio.get_event_loop().time()
        frame_count = 0

        try:
            while True:
                # 检查运行时长
                if duration_seconds:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    if elapsed >= duration_seconds:
                        logger.info(f"达到运行时长 {duration_seconds} 秒，停止读取")
                        break

                # 读取数据帧
                result = self.read_frame()

                if result:
                    channels, _, raw_frame = result
                    frame_count += 1

                    # 每秒打印一次统计
                    if frame_count % 50 == 0:  # 约50fps统计一次
                        rate = frame_count / (asyncio.get_event_loop().time() - start_time)
                        logger.info(f"已接收 {frame_count} 帧，平均速率: {rate:.1f} fps")

                    # 输出原始数据 + 通道分组
                    self.print_raw_frame(raw_frame, channels)

        except KeyboardInterrupt:
            logger.info("收到中断信号，停止读取")
        finally:
            self.disconnect()
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"总共接收 {frame_count} 帧，用时 {elapsed:.2f} 秒，平均速率: {frame_count/elapsed:.1f} fps")


async def main():
    """主函数。"""
    import sys
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
    
    # 配置日志
    logger.remove()
    logger.add(
        lambda msg: print(msg, end=''),
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )

    print("="*60)
    print("SBUS遥控器接收测试程序")
    print("="*60)
    print(f"端口配置: {port} @ 100000 baud (8E2)")
    print("协议: SBUS (16通道 + 2数字通道)")
    print("="*60)
    print("\n提示: 按 Ctrl+C 停止程序\n")

    # 创建接收器
    receiver = SBUSReceiver(
        port=port,
        baudrate=100000,
        invert=False,
        log_path="logs/sbus_raw.log",
    )

    # 开始读取（运行60秒自动停止，或设置为None无限期运行）
    await receiver.start_reading(duration_seconds=60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已退出")
