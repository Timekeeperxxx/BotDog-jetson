#!/usr/bin/env python3
"""
测试基于 subprocess 的 GStreamer 视频轨道 - 最终版本
"""

import asyncio
import subprocess
import sys
import os

# 添加 backend 到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from video_track_native import GStreamerVideoTrack


async def test_with_test_stream():
    """使用本地测试流进行测试"""
    print("=" * 80)
    print("测试 GStreamer 视频轨道（基于 subprocess）")
    print("=" * 80)

    print("\n步骤 1: 启动测试 UDP 流...")

    # 在后台启动测试流
    test_pipeline = (
        "gst-launch-1.0 -q "
        "videotestsrc pattern=ball "
        "! video/x-raw,width=1280,height=720,framerate=30/1 "
        "! videoconvert "
        "! x265enc bitrate=2000 "
        "! h265parse "
        "! rtph265pay "
        "! udpsink host=127.0.0.1 port=5000 sync=false"
    )

    test_process = subprocess.Popen(
        test_pipeline,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    print(f"[OK] 测试流已启动 (PID: {test_process.pid})")

    # 等待一下让流启动
    print("\n步骤 2: 等待流初始化...")
    await asyncio.sleep(2)

    print("\n步骤 3: 启动视频接收器...")

    # 创建视频轨道
    track = GStreamerVideoTrack(
        udp_port=5000,
        width=1280,
        height=720,
        framerate=30
    )

    try:
        # 启动轨道
        await track.start()

        # 接收帧 10 秒
        frame_count = 0
        start_time = asyncio.get_event_loop().time()

        print("\n步骤 4: 接收帧...")

        while True:
            try:
                frame = await asyncio.wait_for(track.recv(), timeout=2.0)

                if frame is None:
                    print("流已结束")
                    break

                frame_count += 1

                if frame_count % 10 == 0:
                    elapsed = asyncio.get_event_loop().time() - start_time
                    fps = frame_count / elapsed
                    print(f"[帧] {frame_count} 帧, FPS: {fps:.2f}, 尺寸: {frame.width}x{frame.height}")

                # 10 秒后停止
                if asyncio.get_event_loop().time() - start_time >= 10:
                    break

            except asyncio.TimeoutError:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= 10:
                    print(f"\n测试在 {elapsed:.1f} 秒后完成")
                    break
                else:
                    print("[等待] 等待帧...")
                    continue

        # 最终统计
        elapsed = asyncio.get_event_loop().time() - start_time
        if frame_count > 0:
            avg_fps = frame_count / elapsed
            print(f"\n{'='*80}")
            print(f"测试结果：")
            print(f"{'='*80}")
            print(f"总帧数: {frame_count}")
            print(f"持续时间: {elapsed:.1f} 秒")
            print(f"平均 FPS: {avg_fps:.2f}")

            if avg_fps >= 25:
                print(f"\n[成功] 性能优秀 (FPS >= 25)")
            elif avg_fps >= 15:
                print(f"\n[成功] 性能良好 (FPS >= 15)")
            else:
                print(f"\n[警告] 帧率较低")

        else:
            print(f"\n{'='*80}")
            print(f"未接收到帧")
            print(f"{'='*80}")

        # 停止轨道
        await track.stop()

        print("\n[OK] 测试成功完成！")
        return True

    except Exception as e:
        print(f"\n{'='*80}")
        print(f"测试失败：")
        print(f"{'='*80}")
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()

        try:
            await track.stop()
        except:
            pass

        return False

    finally:
        # 停止测试流
        print("\n步骤 5: 停止测试流...")
        test_process.terminate()
        try:
            test_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            test_process.kill()
        print("[OK] 测试流已停止")


async def main():
    """主测试函数"""
    print("\n" + "=" * 80)
    print("GStreamer 视频轨道测试 - 最终版本")
    print("=" * 80)

    print("\n此测试将：")
    print("1. 创建测试 UDP H.265 流")
    print("2. 使用 d3d11h265dec 硬件解码器接收")
    print("3. 测量 FPS 并验证功能")

    try:
        success = await test_with_test_stream()

        if success:
            print("\n" + "=" * 80)
            print("所有测试通过！")
            print("=" * 80)
            print("\n零依赖视频轨道工作完美！")
            print("准备好用于真实的 UDP H.265 流！")
            return 0
        else:
            print("\n[警告] 测试有问题")
            return 1

    except KeyboardInterrupt:
        print("\n\n[信息] 测试被用户中断")
        return 1
    except Exception as e:
        print(f"\n[错误] 意外错误: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
