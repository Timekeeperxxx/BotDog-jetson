#!/usr/bin/env python3
"""
Create a test UDP H.265 stream for testing the video track

This generates a test stream using videotestsrc and sends it to UDP port 5000
"""

import subprocess
import time
import sys

def create_test_stream():
    """Create a test UDP H.265 stream"""
    print("=" * 80)
    print("Creating Test UDP H.265 Stream")
    print("=" * 80)

    print("\nPipeline:")
    print("videotestsrc -> x265enc -> H.265 RTP -> UDP port 5000")

    print("\nConfiguration:")
    print("  Source: videotestsrc (test pattern)")
    print("  Encoder: x265enc (H.265)")
    print("  Decoder target: d3d11h265dec (hardware)")
    print("  Output: UDP 127.0.0.1:5000")

    print("\n" + "-" * 80)
    print("Starting test stream...")
    print("Press Ctrl+C to stop")
    print("-" * 80 + "\n")

    # GStreamer pipeline for test stream
    pipeline = (
        "gst-launch-1.0 -v "
        "videotestsrc pattern=ball "
        "! video/x-raw,width=1280,height=720,framerate=30/1 "
        "! videoconvert "
        "! x265enc bitrate=2000 "
        "! h265parse "
        "! rtph265pay "
        "! udpsink host=127.0.0.1 port=5000 sync=false"
    )

    try:
        # Start the test stream
        process = subprocess.Popen(
            pipeline,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print(f"✓ Test stream started (PID: {process.pid})")
        print("\nNow you can run the video track test in another terminal:")
        print("  python test_video_track_native.py")
        print("\nPress Ctrl+C to stop the test stream\n")

        # Wait for interrupt
        process.wait()

    except KeyboardInterrupt:
        print("\n\nStopping test stream...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        print("✓ Test stream stopped")

    except Exception as e:
        print(f"\nError: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(create_test_stream())
