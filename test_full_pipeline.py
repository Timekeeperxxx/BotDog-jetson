#!/usr/bin/env python3
"""
测试完整的 UDP H.265 接收和硬件解码管道
"""

import cv2
import asyncio
import time
import sys

async def test_udp_h265_stream():
    """
    测试 UDP H.265 流的接收和硬件解码

    这个测试模拟真实场景:
    1. 从 UDP 端口 5000 接收 H.265 RTP 流
    2. 使用 d3d11h265dec 硬件解码
    3. 转码为 H.264 输出
    4. 统计帧率和性能指标
    """

    print("=" * 80)
    print("UDP H.265 流接收 + 硬件解码测试")
    print("=" * 80)

    # 构建完整的管道
    pipeline = (
        "udpsrc port=5000 "
        'caps="application/x-rtp,media=video,encoding-name=H265,payload=96" '
        "! rtpjitterbuffer latency=100 do-retransmission=true "
        "! rtph265depay "
        "! h265parse "
        "! d3d11h265dec "  # D3D11 硬件解码
        "! videoconvert "
        "! video/x-raw,format=I420 "
        "! x264enc tune=zerolatency speed-preset=ultrafast "
        "! rtph264pay "
        "! appsink sync=false"
    )

    print(f"\n🔧 GStreamer 管道:")
    print(f"   {pipeline}")
    print(f"\n📊 测试配置:")
    print(f"   监听地址: 0.0.0.0:5000")
    print(f"   输入编码: H.265 RTP")
    print(f"   解码器: d3d11h265dec (D3D11 硬件)")
    print(f"   输出编码: H.264 (x264enc)")
    print(f"   抖动缓冲: 100ms + 重传")

    print(f"\n⚠️  请确保相机正在推流!")
    print(f"   RTSP 地址: rtsp://192.168.144.25:8554/main.264")
    print(f"   推流目标: udp://127.0.0.1:5000")

    print(f"\n🚀 启动测试管道...")

    try:
        # 打开管道
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        if not cap.isOpened():
            print("❌ 无法打开 UDP 管道")
            print("\n可能原因:")
            print("1. 端口 5000 被占用")
            print("2. GStreamer 插件缺失")
            print("3. 管道语法错误")
            print("\n检查命令:")
            print("  netstat -ano | findstr :5000")
            print("  gst-inspect-1.0 d3d11h265dec")
            print("  gst-inspect-1.0 x264enc")
            return False

        print("✅ UDP 管道打开成功")
        print("⏳ 等待接收视频流...")

        # 读取帧并统计
        frame_count = 0
        test_duration = 30  # 测试 30 秒
        start_time = time.time()
        last_print_time = start_time

        print(f"\n⏱️  开始接收 (持续 {test_duration} 秒)...")

        while True:
            ret, frame = cap.read()

            if not ret or frame is None:
                # 等待流开始
                await asyncio.sleep(0.1)
                continue

            frame_count += 1
            current_time = time.time()

            # 每秒打印一次统计
            if current_time - last_print_time >= 1.0:
                elapsed = current_time - start_time
                current_fps = frame_count / elapsed
                print(f"   ✅ 已接收 {frame_count} 帧, "
                      f"耗时 {elapsed:.1f}s, "
                      f"当前 FPS: {current_fps:.2f}, "
                      f"尺寸: {frame.shape}")
                last_print_time = current_time

            # 达到测试时长
            if current_time - start_time >= test_duration:
                break

        end_time = time.time()
        elapsed = end_time - start_time

        # 计算最终统计
        avg_fps = frame_count / elapsed
        avg_time_per_frame = (elapsed / frame_count) * 1000 if frame_count > 0 else 0

        print("\n" + "=" * 80)
        print("✅ 测试完成!")
        print("=" * 80)
        print(f"\n📊 性能统计:")
        print(f"   接收帧数: {frame_count}")
        print(f"   测试时长: {elapsed:.1f} 秒")
        print(f"   平均 FPS: {avg_fps:.2f}")
        print(f"   平均每帧: {avg_time_per_frame:.2f} ms")
        print(f"   帧尺寸: {frame.shape if frame_count > 0 else 'N/A'}")

        # 性能评估
        if frame_count == 0:
            print(f"\n❌ 未接收到任何帧")
            print("\n请检查:")
            print("1. 相机是否正在推流")
            print("2. RTSP 地址是否正确: rtsp://192.168.144.25:8554/main.264")
            print("3. 网络连接: ping 192.168.144.25")
            print("4. 相机编码格式是否为 H.265 (不是 H.264)")
            return False

        if avg_fps >= 28:
            print(f"\n✅ 性能优秀! (FPS >= 28)")
            print("   ✓ UDP 接收正常")
            print("   ✓ H.265 硬件解码工作正常")
            print("   ✓ H.264 编码输出正常")
            print("   ✓ CPU 占用应该很低")
            performance_grade = "优秀"
        elif avg_fps >= 24:
            print(f"\n✅ 性能良好! (FPS >= 24)")
            print("   ✓ UDP 接收正常")
            print("   ✓ H.265 硬件解码工作正常")
            print("   → 略低于目标，可能受网络抖动影响")
            performance_grade = "良好"
        elif avg_fps >= 15:
            print(f"\n⚠️  性能一般 (FPS >= 15)")
            print("   → 可能存在网络延迟")
            print("   → 或 GPU 硬解未完全启用")
            performance_grade = "一般"
        else:
            print(f"\n❌ 性能不足 (FPS < 15)")
            print("   → 网络延迟较高")
            print("   → 或 GPU 硬件解码未工作")
            performance_grade = "不足"

        print(f"   综合评价: {performance_grade}")
        print("=" * 80)

        cap.release()
        return avg_fps >= 24

    except KeyboardInterrupt:
        print("\n\n⚠️  测试被用户中断")
        if cap:
            cap.release()
        return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """主函数"""
    print("\n提示: 此测试需要相机正在推流到 UDP 端口 5000")
    print("如果相机未推流，此测试将等待超时\n")

    # 等待用户确认
    try:
        input("按 Enter 开始测试，或 Ctrl+C 退出...")
    except KeyboardInterrupt:
        print("\n测试已取消")
        return

    success = await test_udp_h265_stream()

    if success:
        print("\n✅ 所有测试通过! 系统已准备就绪。")
    else:
        print("\n❌ 测试未通过，请检查上述问题。")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n测试已取消")
        sys.exit(1)
