#!/usr/bin/env python3
"""
测试 OpenCV GStreamer 支持
"""

import cv2
import sys
import os

def test_opencv_gstreamer():
    """测试 OpenCV 是否支持 GStreamer"""

    print("=" * 80)
    print("OpenCV GStreamer 支持测试")
    print("=" * 80)

    # 检查 OpenCV 版本
    print(f"\n📦 OpenCV 版本: {cv2.__version__}")

    # 检查构建信息
    build_info = cv2.getBuildInformation()
    has_gstreamer = build_info.find('GStreamer') != -1

    print(f"{'✅' if has_gstreamer else '❌'} GStreamer 支持: {'是' if has_gstreamer else '否'}")

    if not has_gstreamer:
        print("\n❌ OpenCV 未编译 GStreamer 支持")
        print("\n解决方案:")
        print("1. 确认 GStreamer 已正确安装")
        print("2. 设置环境变量 GSTREAMER_1_0_ROOT_MSVC_X86_64")
        print("3. 将 GStreamer bin 目录添加到 PATH")
        print("4. 重新安装 opencv-python:")
        print("   pip uninstall opencv-python")
        print("   pip install opencv-python")
        return False

    # 检查 GStreamer 环境
    print("\n🔍 检查 GStreamer 环境...")

    # 检查环境变量
    gst_root = os.environ.get('GSTREAMER_1_0_ROOT_MSVC_X86_64')
    if gst_root:
        print(f"✅ GSTREAMER_1_0_ROOT_MSVC_X86_64: {gst_root}")
    else:
        print("⚠️  GSTREAMER_1_0_ROOT_MSVC_X86_64 未设置")

    # 检查 PATH
    path = os.environ.get('PATH', '')
    if 'gstreamer' in path.lower():
        print("✅ PATH 包含 GStreamer")
    else:
        print("⚠️  PATH 可能不包含 GStreamer bin 目录")

    # 测试简单的 GStreamer 管道
    print("\n🧪 测试 GStreamer 管道...")

    # 使用 videotestsrc 测试
    pipeline = "videotestsrc ! videoconvert ! appsink"
    print(f"管道: {pipeline}")

    try:
        cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

        if not cap.isOpened():
            print("❌ 无法打开 GStreamer 管道")
            print("\n可能原因:")
            print("1. GStreamer 未正确安装")
            print("2. 环境变量未设置")
            print("3. 缺少必要的 GStreamer 插件")
            return False

        print("✅ GStreamer 管道打开成功")

        # 尝试读取一帧
        ret, frame = cap.read()
        if ret and frame is not None:
            print(f"✅ 成功读取测试帧，尺寸: {frame.shape}")
            print(f"   数据类型: {frame.dtype}")
            print(f"   形状: {frame.shape}")
            success = True
        else:
            print("❌ 无法读取帧")
            success = False

        cap.release()

        if success:
            print("\n" + "=" * 80)
            print("✅ OpenCV GStreamer 测试通过!")
            print("=" * 80)
            return True
        else:
            return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_opencv_gstreamer()
    sys.exit(0 if success else 1)
