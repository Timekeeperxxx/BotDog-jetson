#!/bin/bash
# 项目导出脚本 - 准备传输到 Windows 主机

echo "=========================================="
echo "BotDog 项目导出脚本"
echo "=========================================="
echo ""

# 1. 创建导出目录
EXPORT_DIR="/tmp/BotDog_Export"
echo "[1/5] 创建导出目录: $EXPORT_DIR"
rm -rf "$EXPORT_DIR"
mkdir -p "$EXPORT_DIR"

# 2. 复制项目文件（排除虚拟环境、缓存等）
echo "[2/5] 复制项目文件..."
rsync -av --progress \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='node_modules' \
    --exclude='frontend/dist' \
    --exclude='frontend/.next' \
    --exclude='*.log' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='data/*.db' \
    --exclude='data/*.sqlite' \
    /home/frank/Code/Project/BotDog/ \
    "$EXPORT_DIR/BotDog/"

# 3. 创建 Windows 启动脚本
echo "[3/5] 创建 Windows 启动脚本..."
cat > "$EXPORT_DIR/BotDog/start_backend.bat" << 'EOF'
@echo off
REM BotDog 后端启动脚本 (Windows)

echo ==========================================
echo BotDog 后端启动
echo ==========================================

REM 检查 Python 是否安装
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 检查虚拟环境
if not exist "venv" (
    echo [1/3] 创建虚拟环境...
    python -m venv venv
)

REM 激活虚拟环境
echo [2/3] 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装/更新依赖
echo [3/3] 安装依赖...
pip install -r requirements.txt

REM 启动后端
echo.
echo ==========================================
echo 启动后端服务...
echo ==========================================
echo.

uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

pause
EOF

cat > "$EXPORT_DIR/BotDog/start_frontend.bat" << 'EOF'
@echo off
REM BotDog 前端启动脚本 (Windows)

echo ==========================================
echo BotDog 前端启动
echo ==========================================

cd frontend

REM 检查 Node.js 是否安装
node --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Node.js，请先安装 Node.js 18+
    pause
    exit /b 1
)

REM 安装依赖
if not exist "node_modules" (
    echo [1/2] 安装前端依赖...
    call npm install
)

REM 启动前端
echo [2/2] 启动前端开发服务器...
echo.
call npm run dev

pause
EOF

# 4. 创建 README
echo "[4/5] 创建 README..."
cat > "$EXPORT_DIR/BotDog/WINDOWS_SETUP.md" << 'EOF'
# BotDog Windows 环境设置指南

## 前置要求

### 1. Python 环境
- Python 3.8 或更高版本
- 下载地址: https://www.python.org/downloads/
- 安装时勾选 "Add Python to PATH"

### 2. Node.js 环境
- Node.js 18 或更高版本
- 下载地址: https://nodejs.org/

### 3. GStreamer (必需)
- 下载 GStreamer for Windows
- 下载地址: https://gstreamer.freedesktop.org/download/
- 选择: `gstreamer-1.0-msvc-x86_64.msi`
- 安装到默认路径: `C:\gstreamer\1.0\msvc_x86_64`

### 4. 环境变量配置

需要添加以下环境变量：

```
GSTREAMER_ROOT_X86_64=C:\gstreamer\1.0\msvc_x86_64
PATH=%GSTREAMER_ROOT_X86_64%\bin;%PATH%
```

## 快速启动

### 后端启动
双击运行: `start_backend.bat`

或手动启动:
```cmd
cd BotDog
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端启动
双击运行: `start_frontend.bat`

或手动启动:
```cmd
cd BotDog\frontend
npm install
npm run dev
```

## 访问应用

- 后端 API: http://localhost:8000
- 前端界面: http://localhost:5173
- API 文档: http://localhost:8000/docs

## 视频配置

确保 `backend/.env` 文件包含以下配置:

```env
VIDEO_RESOLUTION=1920x1080
VIDEO_FRAMERATE=60
VIDEO_UDP_PORT=19856
VIDEO_BITRATE=8000000
```

## 故障排查

### GStreamer 未找到
```cmd
# 验证 GStreamer 安装
gst-launch-1.0 --version

# 如果提示未找到命令，检查环境变量
echo %GSTREAMER_ROOT_X86_64%
echo %PATH%
```

### Python 依赖安装失败
```cmd
# 升级 pip
python -m pip install --upgrade pip

# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 端口被占用
```cmd
# 查看端口占用
netstat -ano | findstr ":8000"
netstat -ano | findstr ":19856"

# 结束进程
taskkill /F /PID <进程ID>
```
EOF

# 5. 打包
echo "[5/5] 创建压缩包..."
cd "$EXPORT_DIR"
zip -r /tmp/BotDog_Windows.zip BotDog/ -q

echo ""
echo "=========================================="
echo "导出完成！"
echo "=========================================="
echo "导出位置: /tmp/BotDog_Windows.zip"
echo "文件大小: $(du -h /tmp/BotDog_Windows.zip | cut -f1)"
echo ""
echo "传输方式："
echo "1. 通过 VMware 共享文件夹"
echo "2. 通过 U 盘复制"
echo "3. 通过网络共享"
echo "=========================================="
