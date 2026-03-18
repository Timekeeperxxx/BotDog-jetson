import serial
import time

def run_high_speed_sbus(port="COM7"):
    try:
        # 强制设置较大的缓冲区
        ser = serial.Serial(
            port=port,
            baudrate=100000,
            parity=serial.PARITY_EVEN,
            stopbits=serial.STOPBITS_TWO,
            bytesize=serial.EIGHTBITS,
            timeout=0
        )
        ser.set_buffer_size(rx_size=4096) # 尝试增大驱动层缓冲区

        print(f"--- 正在监控 {port} 链路质量 ---")
        buffer = bytearray()
        valid_frames = 0
        error_bytes = 0
        start_time = time.time()

        while True:
            # 1. 一次性读取所有可用字节
            waiting = ser.in_waiting
            if waiting > 0:
                chunk = ser.read(waiting)
                buffer.extend(chunk)

            # 2. 快速滑动窗口解析
            while len(buffer) >= 25:
                if buffer[0] == 0x0F:
                    # 检查 SBUS 帧尾（通常是 0x00，但也可能是状态位）
                    # 只要长度够且帧头对，先解析看看
                    frame = buffer[:25]
                    valid_frames += 1
                    
                    # 每秒统计一次频率
                    elapsed = time.time() - start_time
                    if elapsed >= 1.0:
                        fps = valid_frames / elapsed
                        print(f"\n[统计] 帧率: {fps:.1f} Hz | 错误字节堆积: {error_bytes}")
                        valid_frames = 0
                        error_bytes = 0
                        start_time = time.time()

                    # 提取通道1预览
                    ch1 = (frame[1] | frame[2] << 8) & 0x07FF
                    print(f"\rCH1: {ch1:4d} | 缓冲区长度: {len(buffer):4d}", end="")
                    
                    del buffer[:25]
                else:
                    buffer.pop(0)
                    error_bytes += 1

            # 3. 极短休眠，防止 CPU 100% 但保证响应速度
            time.sleep(0.002)

    except Exception as e:
        print(f"\n发生错误: {e}")
    finally:
        if 'ser' in locals(): ser.close()

if __name__ == "__main__":
    run_high_speed_sbus()