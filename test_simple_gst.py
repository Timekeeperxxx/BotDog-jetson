#!/usr/bin/env python3
"""
Simple OpenCV + GStreamer test
"""

import cv2
import sys

def test_simple_gst():
    """Test simple GStreamer pipelines"""
    print("=" * 80)
    print("OpenCV + GStreamer Simple Test")
    print("=" * 80)

    # Test 1: Simplest pipeline
    print("\nTest 1: videotestsrc -> appsink")
    pipeline1 = "videotestsrc ! videoconvert ! appsink"
    print(f"Pipeline: {pipeline1}")

    cap1 = cv2.VideoCapture(pipeline1, cv2.CAP_GSTREAMER)
    if not cap1.isOpened():
        print("FAILED: Cannot open simple pipeline")
        return False

    ret, frame = cap1.read()
    cap1.release()

    if ret and frame is not None:
        print(f"SUCCESS: Read frame, size: {frame.shape}")
    else:
        print("FAILED: Cannot read frame")
        return False

    # Test 2: Add video format
    print("\nTest 2: videotestsrc with format -> appsink")
    pipeline2 = "videotestsrc ! video/x-raw,width=640,height=480,framerate=30/1 ! videoconvert ! appsink"
    print(f"Pipeline: {pipeline2}")

    cap2 = cv2.VideoCapture(pipeline2, cv2.CAP_GSTREAMER)
    if not cap2.isOpened():
        print("FAILED: Cannot open pipeline with format")
        return False

    ret, frame = cap2.read()
    cap2.release()

    if ret and frame is not None:
        print(f"SUCCESS: Read frame, size: {frame.shape}")
    else:
        print("FAILED: Cannot read frame")
        return False

    # Test 3: H.264 encoding
    print("\nTest 3: videotestsrc -> x264enc -> appsink")
    pipeline3 = "videotestsrc ! videoconvert ! x264enc ! h264parse ! avdec_h264 ! videoconvert ! appsink"
    print(f"Pipeline: {pipeline3}")

    cap3 = cv2.VideoCapture(pipeline3, cv2.CAP_GSTREAMER)
    if not cap3.isOpened():
        print("FAILED: Cannot open H.264 pipeline")
        return False

    ret, frame = cap3.read()
    cap3.release()

    if ret and frame is not None:
        print(f"SUCCESS: Read frame, size: {frame.shape}")
    else:
        print("FAILED: Cannot read frame")
        return False

    # Test 4: Try H.265 (may fail, that's OK)
    print("\nTest 4: videotestsrc -> x265enc -> d3d11h265dec -> appsink")
    pipeline4 = "videotestsrc ! videoconvert ! x265enc ! h265parse ! d3d11h265dec ! videoconvert ! appsink"
    print(f"Pipeline: {pipeline4}")

    cap4 = cv2.VideoCapture(pipeline4, cv2.CAP_GSTREAMER)
    if not cap4.isOpened():
        print("WARNING: Cannot open H.265 pipeline")
        print("This may be normal, OpenCV might not support some H.265 pipelines")
        print("But this does not affect UDP reception functionality")
        return True  # Not a failure

    ret, frame = cap4.read()
    cap4.release()

    if ret and frame is not None:
        print(f"SUCCESS: Read frame, size: {frame.shape}")
    else:
        print("WARNING: H.265 pipeline opened but cannot read frame")
        print("This might be due to x265enc configuration issue")

    print("\n" + "=" * 80)
    print("SUCCESS: OpenCV + GStreamer basic functions work")
    print("=" * 80)
    return True

if __name__ == "__main__":
    success = test_simple_gst()
    sys.exit(0 if success else 1)
