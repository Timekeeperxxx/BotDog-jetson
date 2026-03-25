import time
import sys
from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py.b2.sport.sport_client import SportClient

ChannelFactoryInitialize(0, "ens37")

client = SportClient()
client.SetTimeout(2.0)
client.Init()

print("Calling Move()...", flush=True)
t0 = time.time()
try:
    client.Move(0.3, 0.0, 0.0)
    print(f"Move() returned in {time.time() - t0:.2f}s", flush=True)
except Exception as e:
    print(f"Move() raised exception: {e}", flush=True)
