#!/bin/bash
# 音频播放中转脚本
# 目的：在 systemd 服务环境下，自动找到 PulseAudio 套接字并播放音频
# 用法：bash scripts/play_audio.sh <音频文件路径>

AUDIO_FILE="$1"

if [ -z "$AUDIO_FILE" ]; then
    echo "用法: $0 <音频文件路径>" >&2
    exit 1
fi

if [ ! -f "$AUDIO_FILE" ]; then
    echo "错误：音频文件不存在: $AUDIO_FILE" >&2
    exit 1
fi

# 自动搜索所有已登录用户的 PulseAudio 套接字
PULSE_SOCKET=""
for uid_dir in /run/user/*/; do
    uid=$(basename "$uid_dir")
    socket="$uid_dir/pulse/native"
    if [ -S "$socket" ]; then
        PULSE_SOCKET="$socket"
        XDG_RUNTIME_DIR="$uid_dir"
        break
    fi
done

if [ -n "$PULSE_SOCKET" ]; then
    # 通过 PulseAudio 播放（音质最佳，支持混音）
    export XDG_RUNTIME_DIR
    export PULSE_SERVER="unix:$PULSE_SOCKET"
    paplay "$AUDIO_FILE"
else
    # 降级：直接走 ALSA 默认输出
    aplay "$AUDIO_FILE"
fi
