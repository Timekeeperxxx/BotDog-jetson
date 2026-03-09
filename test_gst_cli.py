#!/usr/bin/env python3
"""
Test GStreamer pipeline using subprocess
"""

import subprocess
import sys
import time

def test_gst_cli():
    """Test GStreamer using CLI tools"""
    print("=" * 80)
    print("GStreamer CLI Test (without OpenCV)")
    print("=" * 80)

    # Test 1: Simple pipeline
    print("\nTest 1: videotestsrc -> fakesink (10 frames)")
    pipeline1 = "gst-launch-1.0 -v videotestsrc ! video/x-raw,width=640,height=480,framerate=30/1 ! fakesink num-buffers=10"
    print(f"Command: {pipeline1}")

    try:
        result = subprocess.run(
            pipeline1,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            print("SUCCESS: Pipeline ran for 10 frames")
        else:
            print(f"FAILED: Return code {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("FAILED: Timeout")
        return False
    except Exception as e:
        print(f"FAILED: {e}")
        return False

    # Test 2: H.264 encoding/decoding
    print("\nTest 2: videotestsrc -> x264enc -> avdec_h264 -> fakesink")
    pipeline2 = "gst-launch-1.0 -v videotestsrc ! videoconvert ! x264enc ! h264parse ! avdec_h264 ! videoconvert ! fakesink num-buffers=30"
    print(f"Command: {pipeline2}")

    try:
        result = subprocess.run(
            pipeline2,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode == 0:
            print("SUCCESS: H.264 pipeline ran for 30 frames")
        else:
            print(f"FAILED: Return code {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print("FAILED: Timeout")
        return False
    except Exception as e:
        print(f"FAILED: {e}")
        return False

    # Test 3: H.265 encoding/decoding
    print("\nTest 3: videotestsrc -> x265enc -> d3d11h265dec -> fakesink")
    pipeline3 = "gst-launch-1.0 -v videotestsrc ! videoconvert ! x265enc ! h265parse ! d3d11h265dec ! videoconvert ! fakesink num-buffers=30"
    print(f"Command: {pipeline3}")

    try:
        start_time = time.time()
        result = subprocess.run(
            pipeline3,
            shell=True,
            capture_output=True,
            text=True,
            timeout=15
        )
        elapsed = time.time() - start_time

        if result.returncode == 0:
            fps = 30 / elapsed
            print(f"SUCCESS: H.265 pipeline ran for 30 frames in {elapsed:.2f}s")
            print(f"Estimated FPS: {fps:.2f}")
        else:
            print(f"FAILED: Return code {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr[:500]}")  # First 500 chars
            return False

    except subprocess.TimeoutExpired:
        print("FAILED: Timeout")
        return False
    except Exception as e:
        print(f"FAILED: {e}")
        return False

    print("\n" + "=" * 80)
    print("SUCCESS: GStreamer CLI tests passed")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = test_gst_cli()
    sys.exit(0 if success else 1)
