#!/usr/bin/env python3
"""
硬件加速视频轨道集成示例

展示如何在现有的 WebRTC 系统中使用新的硬件加速视频轨道
"""

import asyncio
from aiortc import RTCPeerConnection, MediaStreamTrack, RTCSessionDescription
from aiortc.contrib.signaling import TcpSocketSignaling
from backend.video_track_hw import GStreamerVideoSourceFactory


async def create_video_track():
    """
    创建硬件加速视频轨道

    Returns:
        GStreamerVideoTrack: 视频轨道实例
    """
    print("\n" + "="*80)
    print("创建硬件加速视频轨道")
    print("="*80)

    # 创建视频轨道
    track = GStreamerVideoSourceFactory.create_track(
        udp_port=5000,      # UDP 接收端口
        width=1920,         # 1080P
        height=1080,
        framerate=30        # 30fps
    )

    print(f"✅ 视频轨道已创建")
    print(f"   UDP 端口: {track.udp_port}")
    print(f"   分辨率: {track.width}x{track.height}")
    print(f"   帧率: {track.framerate}fps")
    print(f"   解码器: d3d11h265dec (D3D11 硬件)")

    return track


async def run_webrtc_server():
    """
    运行 WebRTC 服务器示例

    展示如何将硬件加速视频轨道集成到 WebRTC 连接中
    """
    print("\n" + "="*80)
    print("WebRTC 服务器示例 - 硬件加速版本")
    print("="*80)

    # 创建视频轨道
    video_track = await create_video_track()

    # 启动视频轨道
    print("\n启动视频轨道...")
    await video_track.start()

    # 等待一下让管道初始化
    await asyncio.sleep(2)

    # 创建 RTCPeerConnection
    pc = RTCPeerConnection()

    # 添加视频轨道
    pc.addTrack(video_track)

    print("✅ 视频轨道已添加到 WebRTC 连接")

    # 这里可以添加信令逻辑
    # 例如: 接收 SDP offer/answer, ICE candidates 等

    print("\n" + "="*80)
    print("服务器运行中...")
    print("="*80)
    print("按 Ctrl+C 停止")

    try:
        # 保持运行
        await asyncio.sleep(3600)  # 运行 1 小时
    except KeyboardInterrupt:
        print("\n\n停止服务器...")

    # 清理
    await pc.close()
    await video_track.stop()

    print("✅ 服务器已停止")


async def test_video_frames():
    """
    测试视频帧接收

    验证硬件加速视频轨道是否正常工作
    """
    print("\n" + "="*80)
    print("测试视频帧接收")
    print("="*80)

    # 创建并启动视频轨道
    video_track = await create_video_track()
    await video_track.start()

    print("\n等待视频流... (5秒)")
    await asyncio.sleep(5)

    # 接收 30 帧进行测试
    print("\n开始接收视频帧...")

    frame_count = 0
    target_frames = 30

    for i in range(target_frames):
        try:
            frame = await asyncio.wait_for(video_track.recv(), timeout=2.0)

            if frame:
                frame_count += 1
                if frame_count % 10 == 0:
                    print(f"   已接收 {frame_count} 帧")
                    print(f"   尺寸: {frame.width}x{frame.height}")
                    print(f"   格式: {frame.format.name}")

        except asyncio.TimeoutError:
            print(f"⚠️  第 {i+1} 帧接收超时")
            continue
        except Exception as e:
            print(f"❌ 接收帧出错: {e}")
            break

    # 统计结果
    print("\n" + "="*80)
    print("测试结果")
    print("="*80)
    print(f"接收帧数: {frame_count}/{target_frames}")

    if frame_count >= target_frames * 0.8:  # 80% 成功率
        print("✅ 测试通过! 视频流正常")
        success = True
    else:
        print("❌ 测试失败! 帧率过低")
        success = False

    # 停止视频轨道
    await video_track.stop()

    return success


async def monitor_performance():
    """
    性能监控示例

    持续监控视频轨道的性能指标
    """
    print("\n" + "="*80)
    print("性能监控示例")
    print("="*80)

    # 创建并启动视频轨道
    video_track = await create_video_track()
    await video_track.start()

    # 监控参数
    duration = 60  # 监控 60 秒
    check_interval = 5  # 每 5 秒检查一次

    print(f"\n开始监控 (持续 {duration} 秒)...")
    print("="*80)

    start_time = asyncio.get_event_loop().time()
    frame_count = 0
    last_check_time = start_time
    last_frame_count = 0

    try:
        while True:
            # 接收帧
            try:
                frame = await asyncio.wait_for(video_track.recv(), timeout=1.0)
                frame_count += 1
            except asyncio.TimeoutError:
                pass

            # 定期检查
            current_time = asyncio.get_event_loop().time()
            elapsed = current_time - start_time

            if elapsed >= duration:
                break

            if current_time - last_check_time >= check_interval:
                # 计算统计数据
                interval_frames = frame_count - last_frame_count
                interval_fps = interval_frames / check_interval
                total_fps = frame_count / elapsed

                print(f"\n⏱️  监控报告 (T+{int(elapsed)}s):")
                print(f"   总帧数: {frame_count}")
                print(f"   总平均 FPS: {total_fps:.2f}")
                print(f"   近期 FPS: {interval_fps:.2f}")
                print(f"   轨道活跃: {'是' if video_track.active else '否'}")

                last_check_time = current_time
                last_frame_count = frame_count

    except KeyboardInterrupt:
        print("\n\n监控被用户中断")

    finally:
        # 最终统计
        elapsed = asyncio.get_event_loop().time() - start_time
        avg_fps = frame_count / elapsed if elapsed > 0 else 0

        print("\n" + "="*80)
        print("最终统计")
        print("="*80)
        print(f"监控时长: {elapsed:.1f} 秒")
        print(f"总帧数: {frame_count}")
        print(f"平均 FPS: {avg_fps:.2f}")

        # 性能评级
        if avg_fps >= 28:
            grade = "优秀 ✅"
        elif avg_fps >= 24:
            grade = "良好 ✅"
        elif avg_fps >= 15:
            grade = "一般 ⚠️"
        else:
            grade = "不足 ❌"

        print(f"性能评级: {grade}")
        print("="*80)

        # 停止视频轨道
        await video_track.stop()


def main():
    """
    主函数 - 提供多个使用示例
    """
    import sys

    print("\n" + "="*80)
    print("硬件加速视频轨道 - 集成示例")
    print("="*80)

    print("\n请选择示例:")
    print("1. 测试视频帧接收")
    print("2. 性能监控 (60秒)")
    print("3. WebRTC 服务器示例")

    try:
        choice = input("\n请输入选项 (1/2/3): ").strip()

        if choice == "1":
            print("\n运行示例 1: 测试视频帧接收")
            success = asyncio.run(test_video_frames())
            sys.exit(0 if success else 1)

        elif choice == "2":
            print("\n运行示例 2: 性能监控")
            asyncio.run(monitor_performance())

        elif choice == "3":
            print("\n运行示例 3: WebRTC 服务器")
            asyncio.run(run_webrtc_server())

        else:
            print("❌ 无效选项")
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\n示例已取消")
        sys.exit(1)


if __name__ == "__main__":
    main()
