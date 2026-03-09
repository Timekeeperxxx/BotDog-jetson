#!/usr/bin/env python3
"""
测试 H.265 硬件解码性能
"""

import cv2
import time
import sys

def test_h265_decode():
    """测试 H.265 硬件解码性能"""

    print("=" * 80)
    print("H.265 硬件解码性能测试")
    print("=" * 80)

    # 测试管道: 生成 H.265 -> 硬件解码 -> 读取帧
    pipeline = (
        "videotestsrc pattern=ball ! "
        "video/x-raw,width=1920,height=1080,framerate=30/1 ! "
        "videoconvert ! "
        "x265enc ! "  # 编码为 H.265
        "h265parse ! "
        "d3d11h265dec ! "  # D3D11 硬件解码
        "videoconvert ! "
        "appsink"
    )

    print(f"\n🔧 测试管道:")
    print(f"   {pipeline}")
    print(f"\n📊 测试参数:")
    print(f"   分辨率: 1920x1080 (1080P)")
    print(f"   帧率: 30fps")
    print(f"   编解码: H.265 (生成) -> H.265 (硬件解码)")
    print(f"   解码器: d3d11h265dec (D3D11)")

    print("\n🚀 开始测试...")

    try:
        # 打开管道
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        if not cap.isOpened():
            print("❌ 无法打开管道")
            print("\n可能原因:")
            print("1. 缺少 x265enc 编码器")
            print("2. 缺少 d3d11h265dec 解码器")
            print("3. GPU 驱动不支持硬件解码")
            print("\n检查命令:")
            print("  gst-inspect-1.0 x265enc")
            print("  gst-inspect-1.0 d3d11h265dec")
            return False

        print("✅ 管道打开成功")

        # 测试读取 100 帧
        frame_count = 0
        target_frames = 100
        start_time = time.time()

        print(f"\n⏱️  开始读取 {target_frames} 帧...")

        for i in range(target_frames):
            ret, frame = cap.read()
            if not ret or frame is None:
                print(f"❌ 读取第 {i} 帧失败")
                break

            frame_count += 1

            # 每 20 帧显示一次进度
            if (i + 1) % 20 == 0:
                elapsed = time.time() - start_time
                current_fps = (i + 1) / elapsed
                print(f"   已读取 {i + 1} 帧, 当前 FPS: {current_fps:.2f}")

        end_time = time.time()
        elapsed = end_time - start_time

        # 计算性能指标
        avg_fps = frame_count / elapsed
        avg_time_per_frame = (elapsed / frame_count) * 1000  # 毫秒

        print("\n" + "=" * 80)
        print("✅ 测试完成!")
        print("=" * 80)
        print(f"\n📊 性能指标:")
        print(f"   读取帧数: {frame_count}/{target_frames}")
        print(f"   总耗时: {elapsed:.2f} 秒")
        print(f"   平均 FPS: {avg_fps:.2f}")
        print(f"   平均每帧耗时: {avg_time_per_frame:.2f} ms")
        print(f"   目标帧率: 30 FPS")

        # 性能评估
        if avg_fps >= 28:
            print(f"\n✅ 性能优秀! (FPS >= 28)")
            print("   ✓ GPU 硬件解码工作正常")
            print("   ✓ CPU 占用应该很低")
            performance_grade = "优秀"
        elif avg_fps >= 24:
            print(f"\n✅ 性能良好! (FPS >= 24)")
            print("   ✓ GPU 硬件解码工作正常")
            print("   → 略低于目标，可能受系统负载影响")
            performance_grade = "良好"
        elif avg_fps >= 15:
            print(f"\n⚠️  性能一般 (FPS >= 15)")
            print("   → GPU 硬件解码可能未完全启用")
            print("   → 或系统负载较高")
            performance_grade = "一般"
        else:
            print(f"\n❌ 性能不足 (FPS < 15)")
            print("   → GPU 硬件解码可能未工作")
            print("   → 可能在使用软件解码")
            performance_grade = "不足"

        print(f"   综合评价: {performance_grade}")
        print("=" * 80)

        cap.release()

        return avg_fps >= 24

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_h265_decode()
    sys.exit(0 if success else 1)
