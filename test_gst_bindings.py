#!/usr/bin/env python3
"""
Test GStreamer Python bindings
"""

import sys
import os

print("=" * 80)
print("Testing GStreamer Python Bindings")
print("=" * 80)

# Add GStreamer lib path to sys.path
gst_lib_path = r"C:\Program Files\gstreamer\1.0\msvc_x86_64\lib\gstreamer-1.0"
if gst_lib_path not in sys.path:
    sys.path.insert(0, gst_lib_path)

print(f"\nAdded to sys.path: {gst_lib_path}")

# Try different import methods
print("\n" + "-" * 80)
print("Method 1: Try importing gi.repository")
print("-" * 80)

try:
    import gi
    print("✓ Step 1: imported gi")

    gi.require_version("Gst", "1.0")
    print("✓ Step 2: required GStreamer 1.0")

    from gi.repository import Gst
    print("✓ Step 3: imported Gst")

    Gst.init(None)
    print("✓ Step 4: initialized GStreamer")

    version = Gst.version_string()
    print(f"\n✅ SUCCESS! GStreamer version: {version}")

    # Test creating a pipeline
    print("\nTesting pipeline creation...")
    pipeline_str = "videotestsrc ! fakesink"
    pipeline = Gst.parse_launch(pipeline_str)
    if pipeline:
        print(f"✓ Created pipeline: {pipeline_str}")
        print("✅ All tests passed!")
        sys.exit(0)
    else:
        print("✗ Failed to create pipeline")
        sys.exit(1)

except ImportError as e:
    print(f"✗ ImportError: {e}")
    print("\nPyGObject is not installed or not accessible")
    print("\nSolution: Install PyGObject wheel")
    print("1. Download from: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pygobject")
    print("2. Or use conda: conda install pygobject")
    sys.exit(1)

except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
