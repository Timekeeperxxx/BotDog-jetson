#!/usr/bin/env python3
"""
Test GStreamer stdout output capabilities
"""

import subprocess
import sys

def test_gst_stdout():
    """Test GStreamer output to stdout"""
    print("=" * 80)
    print("Testing GStreamer stdout output")
    print("=" * 80)

    # Test 1: Simple pipeline with fakesink
    print("\nTest 1: videotestsrc -> fakesink")
    pipeline1 = "gst-launch-1.0 videotestsrc num-buffers=10 ! fakesink"

    result = subprocess.run(
        pipeline1,
        shell=True,
        capture_output=True,
        text=True,
        timeout=5
    )

    if result.returncode == 0:
        print("[PASS] Test 1: Basic pipeline works")
    else:
        print("[FAIL] Test 1 failed")
        print(f"Error: {result.stderr}")
        return False

    # Test 2: Check if we can capture RGB output
    print("\nTest 2: videotestsrc -> RGB -> fdsink fd=1")
    pipeline2 = "gst-launch-1.0 videotestsrc num-buffers=5 ! video/x-raw,format=RGB,width=320,height=240 ! fdsink fd=1"

    result = subprocess.run(
        pipeline2,
        shell=True,
        capture_output=True,
        timeout=5
    )

    print(f"Return code: {result.returncode}")
    print(f"Stdout size: {len(result.stdout)} bytes")
    print(f"Stderr size: {len(result.stderr)} bytes")

    if len(result.stdout) > 0:
        print("[PASS] Test 2: Got data from stdout")
        expected_size = 320 * 240 * 3 * 5  # 5 frames, RGB
        print(f"Expected: {expected_size} bytes, Got: {len(result.stdout)} bytes")

        if len(result.stdout) >= expected_size * 0.8:
            print("[INFO] Data size looks correct")
            # Show first 100 bytes
            print(f"First 100 bytes (hex): {result.stdout[:100].hex()}")
        else:
            print("[WARN] Data size is smaller than expected")
    else:
        print("[FAIL] Test 2: No data from stdout")
        if result.stderr:
            print(f"Error: {result.stderr[:500]}")

    # Test 3: Try with JPEG encoding
    print("\nTest 3: videotestsrc -> jpegenc -> multipartmux -> fdsink")
    pipeline3 = 'gst-launch-1.0 videotestsrc num-buffers=5 ! video/x-raw,width=320,height=240 ! jpegenc ! multipartmux boundary="gst" ! fdsink fd=1'

    result = subprocess.run(
        pipeline3,
        shell=True,
        capture_output=True,
        timeout=5
    )

    print(f"Return code: {result.returncode}")
    print(f"Stdout size: {len(result.stdout)} bytes")

    if len(result.stdout) > 0:
        print("[PASS] Test 3: Got multipart JPEG data")

        # Check for markers
        if b"--gst" in result.stdout:
            print("[INFO] Found boundary markers")
        if b"Content-Type" in result.stdout:
            print("[INFO] Found Content-Type headers")
        if b"JFIF" in result.stdout or b"Exif" in result.stdout:
            print("[INFO] Found JPEG data")

        # Show first 200 bytes
        print(f"First 200 bytes:\n{result.stdout[:200]}")
    else:
        print("[FAIL] Test 3 failed")
        if result.stderr:
            print(f"Error: {result.stderr[:500]}")

    print("\n" + "=" * 80)
    print("Test completed")
    print("=" * 80)

    return True

if __name__ == "__main__":
    try:
        success = test_gst_stdout()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
