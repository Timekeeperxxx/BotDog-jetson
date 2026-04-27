import asyncio

async def test():
    print("开始测试播放音频...")
    proc = await asyncio.create_subprocess_exec(
        "aplay", "-D", "plughw:3,0", "assets/13282.wav"
    )
    await proc.wait()
    print(f"播放结束，退出码: {proc.returncode}")

asyncio.run(test())
