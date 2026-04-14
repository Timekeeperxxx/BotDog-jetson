import time
import sys
import signal

def handle_sigint(sig, frame):
    print("Mock audio stopped.")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_sigint)
signal.signal(signal.SIGTERM, handle_sigint)

print("Playing mock audio (alert.wav) in loop...")
while True:
    time.sleep(1)
