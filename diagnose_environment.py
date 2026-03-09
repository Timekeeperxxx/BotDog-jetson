#!/usr/bin/env python3
"""
GStreamer 环境诊断工具

快速检查 GStreamer 和相关依赖是否正确安装和配置
"""

import subprocess
import sys
import os
import shutil

def run_command(cmd, description):
    """运行命令并返回结果"""
    print(f"\n{'='*80}")
    print(f"检查: {description}")
    print(f"命令: {cmd}")
    print(f"{'='*80}")

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print(f"✅ 成功")
            if result.stdout.strip():
                print(f"输出:\n{result.stdout}")
            return True
        else:
            print(f"❌ 失败 (返回码: {result.returncode})")
            if result.stderr.strip():
                print(f"错误:\n{result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print(f"❌ 超时")
        return False
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False

def check_file_exists(filepath, description):
    """检查文件是否存在"""
    print(f"\n{'='*80}")
    print(f"检查: {description}")
    print(f"路径: {filepath}")
    print(f"{'='*80}")

    if os.path.exists(filepath):
        print(f"✅ 存在")
        return True
    else:
        print(f"❌ 不存在")
        return False

def check_env_var(var_name, description):
    """检查环境变量"""
    print(f"\n{'='*80}")
    print(f"检查: {description}")
    print(f"变量: {var_name}")
    print(f"{'='*80}")

    value = os.environ.get(var_name)
    if value:
        print(f"✅ 已设置: {value}")
        return True
    else:
        print(f"❌ 未设置")
        return False

def main():
    """主诊断流程"""
    print("="*80)
    print("GStreamer 环境诊断工具")
    print("="*80)
    print("\n这个工具将检查:")
    print("1. GStreamer 安装")
    print("2. 环境变量配置")
    print("3. 关键插件可用性")
    print("4. Python 依赖")
    print("5. OpenCV GStreamer 支持")
    print("\n开始诊断...\n")

    results = []

    # 1. 检查 GStreamer 安装
    results.append(run_command(
        "gst-inspect-1.0 --version",
        "GStreamer 版本"
    ))

    # 2. 检查环境变量
    results.append(check_env_var(
        "GSTREAMER_1_0_ROOT_MSVC_X86_64",
        "GStreamer 根目录环境变量"
    ))

    # 3. 检查关键插件
    results.append(run_command(
        "gst-inspect-1.0 d3d11h265dec",
        "D3D11 H.265 解码器"
    ))

    results.append(run_command(
        "gst-inspect-1.0 x264enc",
        "H.264 编码器"
    ))

    results.append(run_command(
        "gst-inspect-1.0 udpsrc",
        "UDP 源插件"
    ))

    results.append(run_command(
        "gst-inspect-1.0 appsink",
        "App Sink 插件"
    ))

    # 4. 检查 Python 依赖
    print("\n" + "="*80)
    print("检查: Python 依赖")
    print("="*80)

    try:
        import cv2
        print(f"✅ OpenCV: {cv2.__version__}")
        results.append(True)
    except ImportError as e:
        print(f"❌ OpenCV: {e}")
        results.append(False)

    try:
        import numpy
        print(f"✅ NumPy: {numpy.__version__}")
        results.append(True)
    except ImportError as e:
        print(f"❌ NumPy: {e}")
        results.append(False)

    try:
        import av
        print(f"✅ PyAV: {av.__version__}")
        results.append(True)
    except ImportError as e:
        print(f"❌ PyAV: {e}")
        results.append(False)

    try:
        from aiortc import MediaStreamTrack
        print(f"✅ aiortc: 已安装")
        results.append(True)
    except ImportError as e:
        print(f"❌ aiortc: {e}")
        results.append(False)

    # 5. 检查 OpenCV GStreamer 支持
    print("\n" + "="*80)
    print("检查: OpenCV GStreamer 支持")
    print("="*80)

    try:
        import cv2
        build_info = cv2.getBuildInformation()
        has_gstreamer = 'GStreamer' in build_info

        if has_gstreamer:
            print(f"✅ OpenCV 已编译 GStreamer 支持")
            results.append(True)
        else:
            print(f"❌ OpenCV 未编译 GStreamer 支持")
            print(f"   可能需要重新安装 OpenCV")
            results.append(False)
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        results.append(False)

    # 总结
    print("\n" + "="*80)
    print("诊断总结")
    print("="*80)

    total = len(results)
    passed = sum(results)
    failed = total - passed

    print(f"\n总检查项: {total}")
    print(f"✅ 通过: {passed}")
    print(f"❌ 失败: {failed}")

    if failed == 0:
        print("\n🎉 所有检查通过! 系统已准备就绪。")
        print("\n下一步:")
        print("1. 运行: python test_h265_decode.py")
        print("2. 运行: python test_full_pipeline.py")
        return 0
    else:
        print("\n⚠️  存在问题需要解决")
        print("\n常见解决方案:")
        print("1. 安装 GStreamer:")
        print("   下载: https://gstreamer.freedesktop.org/download/")
        print("   安装: gstreamer-1.0-msvc-x86_64.msi")
        print("\n2. 设置环境变量:")
        print("   运行: setup_gstreamer_env.bat")
        print("\n3. 安装 Python 依赖:")
        print("   pip install -r requirements.txt")
        print("\n4. 重启命令提示符以生效环境变量")
        return 1

if __name__ == "__main__":
    sys.exit(main())
