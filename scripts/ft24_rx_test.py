import argparse
import time
from typing import Optional

import serial

SBUS_FRAME_LEN = 25
IBUS_FRAME_LEN = 32


def _decode_sbus(frame: bytes) -> Optional[list[int]]:
    if len(frame) != SBUS_FRAME_LEN:
        return None
    if frame[0] != 0x0F or frame[-1] != 0x00:
        return None

    data = frame[1:23]
    ch = [0] * 16
    ch[0] = (data[0] | data[1] << 8) & 0x07FF
    ch[1] = (data[1] >> 3 | data[2] << 5) & 0x07FF
    ch[2] = (data[2] >> 6 | data[3] << 2 | data[4] << 10) & 0x07FF
    ch[3] = (data[4] >> 1 | data[5] << 7) & 0x07FF
    ch[4] = (data[5] >> 4 | data[6] << 4) & 0x07FF
    ch[5] = (data[6] >> 7 | data[7] << 1 | data[8] << 9) & 0x07FF
    ch[6] = (data[8] >> 2 | data[9] << 6) & 0x07FF
    ch[7] = (data[9] >> 5 | data[10] << 3) & 0x07FF
    ch[8] = (data[11] | data[12] << 8) & 0x07FF
    ch[9] = (data[12] >> 3 | data[13] << 5) & 0x07FF
    ch[10] = (data[13] >> 6 | data[14] << 2 | data[15] << 10) & 0x07FF
    ch[11] = (data[15] >> 1 | data[16] << 7) & 0x07FF
    ch[12] = (data[16] >> 4 | data[17] << 4) & 0x07FF
    ch[13] = (data[17] >> 7 | data[18] << 1 | data[19] << 9) & 0x07FF
    ch[14] = (data[19] >> 2 | data[20] << 6) & 0x07FF
    ch[15] = (data[20] >> 5 | data[21] << 3) & 0x07FF
    return ch


def _decode_ibus(frame: bytes) -> Optional[tuple[list[int], bool]]:
    if len(frame) != IBUS_FRAME_LEN:
        return None
    if frame[0] != 0x20:
        return None

    checksum = (frame[31] << 8) | frame[30]
    calc = (0xFFFF - (sum(frame[:30]) & 0xFFFF)) & 0xFFFF
    checksum_ok = checksum == calc

    ch = []
    for i in range(14):
        lo = frame[2 + i * 2]
        hi = frame[3 + i * 2]
        ch.append((hi << 8) | lo)

    return ch, checksum_ok


def _print_channels(label: str, channels: list[int]) -> None:
    shown = " | ".join(f"{v:4d}" for v in channels[:16])
    print(f"\r{label} 通道1-16: {shown}", end="")


def _monitor_sbus(port: str, duration: Optional[float], invert: bool) -> None:
    with serial.Serial(
        port=port,
        baudrate=100000,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_EVEN,
        stopbits=serial.STOPBITS_TWO,
        timeout=0,
    ) as ser:
        print(f"监听中 {port} (SBUS){' invert' if invert else ''}...")
        buffer = bytearray()
        start = time.time()

        while True:
            waiting = ser.in_waiting
            if waiting > 0:
                buffer.extend(ser.read(waiting))

            while len(buffer) >= SBUS_FRAME_LEN:
                if buffer[0] in (0x0F, 0xF0):
                    frame = bytes(buffer[:SBUS_FRAME_LEN])
                    if buffer[0] == 0xF0 or invert:
                        frame = bytes(b ^ 0xFF for b in frame)
                    channels = _decode_sbus(frame)
                    if channels:
                        _print_channels("SBUS", channels)
                    del buffer[:SBUS_FRAME_LEN]
                else:
                    buffer.pop(0)

            if duration is not None and time.time() - start >= duration:
                print()
                return
            time.sleep(0.001)


def _monitor_ibus(port: str, baud: int, duration: Optional[float]) -> None:
    with serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0,
    ) as ser:
        print(f"监听中 {port} (iBUS @ {baud})...")
        buffer = bytearray()
        start = time.time()

        while True:
            waiting = ser.in_waiting
            if waiting > 0:
                buffer.extend(ser.read(waiting))

            while len(buffer) >= IBUS_FRAME_LEN:
                if buffer[0] == 0x20:
                    frame = bytes(buffer[:IBUS_FRAME_LEN])
                    decoded = _decode_ibus(frame)
                    if decoded:
                        channels, checksum_ok = decoded
                        label = "iBUS" if checksum_ok else "iBUS?"
                        _print_channels(label, channels)
                    del buffer[:IBUS_FRAME_LEN]
                else:
                    buffer.pop(0)

            if duration is not None and time.time() - start >= duration:
                print()
                return
            time.sleep(0.001)


def _monitor_raw(
    port: str,
    baud: int,
    duration: float,
    output: str,
    parity: str,
    stopbits: int,
    with_time: bool,
) -> None:
    parity_map = {
        "none": serial.PARITY_NONE,
        "even": serial.PARITY_EVEN,
        "odd": serial.PARITY_ODD,
    }
    stop_map = {1: serial.STOPBITS_ONE, 2: serial.STOPBITS_TWO}

    with serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=parity_map[parity],
        stopbits=stop_map[stopbits],
        timeout=0,
    ) as ser:
        mode = "RAW+T" if with_time else "RAW"
        print(f"{mode} 记录中 {port} @ {baud}, parity={parity}, stopbits={stopbits} -> {output}")
        start = time.time()
        total = 0

        if with_time:
            with open(output, "w", encoding="utf-8") as out:
                while time.time() - start < duration:
                    waiting = ser.in_waiting
                    if waiting:
                        data = ser.read(waiting)
                        now = time.time()
                        for b in data:
                            out.write(f"{now:.6f} {b}\n")
                        total += len(data)
                    time.sleep(0.001)
        else:
            with open(output, "wb") as out:
                while time.time() - start < duration:
                    waiting = ser.in_waiting
                    if waiting:
                        data = ser.read(waiting)
                        out.write(data)
                        total += len(data)
                    time.sleep(0.001)

        print(f"RAW 结束：写入 {total} 字节")


def main() -> int:
    parser = argparse.ArgumentParser(description="FT24 RX SBUS/iBUS 监听")
    parser.add_argument("--port", default="COM7", help="串口端口名，例如 COM7")
    parser.add_argument("--mode", choices=["sbus", "ibus", "raw"], default="sbus")
    parser.add_argument("--baud", type=int, default=None, help="串口波特率")
    parser.add_argument("--invert", action="store_true", help="SBUS 信号反相")
    parser.add_argument("--duration", type=float, default=None, help="监听时长（秒，默认持续）")
    parser.add_argument("--output", default="raw_dump.bin", help="RAW 输出文件")
    parser.add_argument("--parity", choices=["none", "even", "odd"], default="none")
    parser.add_argument("--stopbits", type=int, choices=[1, 2], default=1)
    parser.add_argument("--with-time", action="store_true", help="RAW 记录时间戳")
    args = parser.parse_args()

    if args.mode == "sbus":
        _monitor_sbus(args.port, duration=args.duration, invert=args.invert)
    elif args.mode == "ibus":
        baud = args.baud or 115200
        _monitor_ibus(args.port, baud=baud, duration=args.duration)
    else:
        if args.duration is None:
            raise SystemExit("raw 模式需要 --duration")
        baud = args.baud or 57600
        _monitor_raw(
            args.port,
            baud=baud,
            duration=args.duration,
            output=args.output,
            parity=args.parity,
            stopbits=args.stopbits,
            with_time=args.with_time,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
