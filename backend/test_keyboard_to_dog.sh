#!/bin/bash
# 键盘直控机器狗测试启动脚本
# 必须先设置 CycloneDDS 环境变量，再启动 Python，否则会报 DDS_RETCODE_PRECONDITION_NOT_MET

export CYCLONEDDS_HOME=$HOME/cyclonedds/install
export LD_LIBRARY_PATH=$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}

echo "=> CYCLONEDDS_HOME: $CYCLONEDDS_HOME"
echo "=> LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
echo ""

# 进入项目根目录，确保 .env 能被正确加载
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

source .venv/bin/activate

python backend/test_keyboard_to_dog.py "$@"
