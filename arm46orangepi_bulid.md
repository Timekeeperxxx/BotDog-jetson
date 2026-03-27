# BotDog 在 OrangePi 5 Ultra 上的完整部署文档

> 适用对象：
>
> - 开发板：OrangePi 5 Ultra
> - 系统：Linux / Ubuntu / Debian 系
> - 项目：BotDog
> - 目标：从本地运行、模拟模式、到 Unitree B2 真机联调、AI、视频链路的完整部署
>
> 本文档基于本次排障和部署过程整理，包含实际踩坑记录与推荐顺序。

---

## 1. 总体部署目标

这个项目不是单独一个 Python 服务，而是一套完整系统，主要包含：

- FastAPI 后端
- React + Vite 前端
- SQLite 数据库
- 模拟遥测 / 真机遥测
- Unitree B2 真机控制适配
- YOLO AI 检测
- RTSP -> FFmpeg -> MediaMTX -> WHEP 视频链路

建议部署顺序：

1. 基础环境准备
2. Python 3.12 安装
3. 后端启动
4. 前端启动
5. 模拟模式跑通
6. Unitree SDK + CycloneDDS 安装
7. 真机网络配置
8. 真机接入联调
9. YOLO 模型准备
10. 视频链路安装与验证

不要一开始就直接上真机。
先把“前后端 + 数据库 + 模拟模式”跑通，再切真机。

---

## 2. 目录约定

以下命令默认项目目录为：

```bash
~/Code/Project/BOTDOG/BotDog
```

如果你的实际目录不同，请自行替换。

---

## 3. 基础系统准备

先更新系统：

```bash
sudo apt update
sudo apt upgrade -y
```

安装常用工具：

```bash
sudo apt install -y \
  build-essential wget curl git ca-certificates cmake pkg-config \
  zlib1g-dev libncurses5-dev libgdbm-dev libnss3-dev libssl-dev \
  libreadline-dev libffi-dev libsqlite3-dev libbz2-dev liblzma-dev \
  tk-dev uuid-dev libgdbm-compat-dev xz-utils ffmpeg
```

说明：

- `ffmpeg` 是视频链路必须依赖
- `cmake`、`build-essential` 是后面编译 CycloneDDS 必须依赖

---

## 4. Python 3.12 安装

项目要求 Python 3.12+。
如果系统默认只有 3.10，不建议替换系统 Python，而是额外安装 Python 3.12 与系统版本并存。

### 4.1 优先检查系统仓库是否有 3.12

```bash
sudo apt update
apt-cache policy python3.12
```

如果有候选版本，直接安装：

```bash
sudo apt install -y python3.12 python3.12-venv python3.12-dev
python3.12 --version
```

### 4.2 如果系统仓库没有，源码安装

```bash
cd /tmp
wget https://www.python.org/ftp/python/3.12.8/Python-3.12.8.tgz
tar -xzf Python-3.12.8.tgz
cd Python-3.12.8
./configure --prefix=/usr/local --with-ensurepip=install
make -j2
sudo make altinstall
python3.12 --version
```

> 注意：一定要使用 `make altinstall`，不要替换系统默认 `python3`。

### 4.3 pip 缺失时的处理

如果出现：

```bash
bash: pip: command not found
```

请用下面方式处理：

```bash
python3.12 -m ensurepip --upgrade
python3.12 -m pip --version
```

后续尽量使用：

```bash
python -m pip install ...
```

不要依赖裸 `pip` 命令。

---

## 5. 创建虚拟环境并安装项目依赖

```bash
cd ~/Code/Project/BOTDOG/BotDog
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt
```

如果你已经装过依赖，重复执行不会有问题。

---

## 6. 后端部署

### 6.1 创建环境配置文件

```bash
cd ~/Code/Project/BOTDOG/BotDog
cp backend/.env.example backend/.env
```

初始建议先用模拟模式，`backend/.env` 至少确认这些值：

```ini
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

MAVLINK_SOURCE=simulation
SIMULATION_WORKER_ENABLED=true
AI_ENABLED=false
CONTROL_ADAPTER_TYPE=simulated
```

### 6.2 数据库初始化前的目录准备

项目默认数据库路径为：

```ini
sqlite+aiosqlite:///./data/botdog.db
```

所以必须先创建 `data/` 目录：

```bash
mkdir -p data
chmod u+rwx data
sudo chown -R orangepi:orangepi data
```

### 6.3 数据库初始化

这个项目有一个已知坑：

- README 写的是 `python scripts/init_db.py`
- 但脚本本身 Python 导入路径处理有问题
- 所以推荐用 `PYTHONPATH=.` 方式运行

正确初始化方式：

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
PYTHONPATH=. python scripts/init_db.py
```

### 6.4 启动后端

推荐这样启动：

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
PYTHONPATH=. python run_backend.py
```

### 6.5 后端验证

浏览器打开：

```text
http://<OrangePi_IP>:8000/api/docs
http://<OrangePi_IP>:8000/api/v1/system/health
```

说明：

- 文档地址是 `/api/docs`
- 不是裸 `/docs`

---

## 7. 前端部署

### 7.1 安装依赖

如果运行 `npm run dev` 报：

```bash
vite: not found
```

说明前端依赖没装。

正确步骤：

```bash
cd ~/Code/Project/BOTDOG/BotDog/frontend
node -v
npm -v
rm -rf node_modules package-lock.json
npm install
```

项目建议 Node.js 18+，更稳是 20。

### 7.2 配置前端环境变量

```bash
cd ~/Code/Project/BOTDOG/BotDog/frontend
cp .env.example .env
nano .env
```

建议改成：

```ini
VITE_API_BASE_URL=http://<OrangePi_IP>:8000
VITE_WHEP_URL=
```

如果后面视频链路完成，再把 `VITE_WHEP_URL` 改回实际地址。

### 7.3 启动前端

```bash
cd ~/Code/Project/BOTDOG/BotDog/frontend
npm run dev -- --host 0.0.0.0
```

浏览器打开：

```text
http://<OrangePi_IP>:5174
```

---

## 8. 模拟模式验收

在没接真机前，先用模拟模式验收基础链路。

### 8.1 建议检查项

1. 前端页面可打开
2. 后端健康检查正常
3. WebSocket 正常连接
4. 遥测数据持续刷新
5. 配置修改能生效
6. 数据库能写入配置和事件

### 8.2 数据库验证

```bash
sqlite3 data/botdog.db "SELECT key, value, value_type FROM system_configs;"
sqlite3 data/botdog.db "SELECT event_type, created_at FROM events ORDER BY created_at DESC LIMIT 10;"
```

### 8.3 建议运行验收测试

```bash
python acceptance_test.py
```

如果模拟模式都没跑通，不建议继续上真机。

---

## 9. 切换到真机前的结论

达到以下条件，才算具备“可以开始真机联调”的前提：

- Python 3.12 环境已稳定
- 后端正常运行
- 前端正常运行
- 数据库初始化正常
- 模拟模式正常
- 你已经能稳定访问开发板页面

但这还不代表“所有功能已经正常运行”。

在真机接入前，仍需补齐：

- CycloneDDS
- Unitree SDK
- 真机网卡配置
- 真机控制验证
- 真机遥测验证
- 视频链路验证
- AI 链路验证

---

## 10. Unitree B2 真机接入配置

你的真机网口名称是：

```text
enP3p49s0
```

这是关键配置项。

### 10.1 修改 backend/.env

将 `backend/.env` 改成至少如下内容：

```ini
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

MAVLINK_SOURCE=mavlink
SIMULATION_WORKER_ENABLED=false

CONTROL_ADAPTER_TYPE=unitree_b2
UNITREE_NETWORK_IFACE=enP3p49s0

UNITREE_B2_VX=0.2
UNITREE_B2_VYAW=0.3

AI_ENABLED=false
```

说明：

- `SIMULATION_WORKER_ENABLED=false` 防止模拟数据继续运行
- `CONTROL_ADAPTER_TYPE=unitree_b2` 切到 B2 控制适配器
- `UNITREE_NETWORK_IFACE=enP3p49s0` 使用真机网口
- `UNITREE_B2_VX`、`UNITREE_B2_VYAW` 首次联调建议低速

### 10.2 为什么还保留 `MAVLINK_SOURCE=mavlink`

虽然 B2 实际控制和遥测主要走 DDS / SDK，但代码里是否启动部分 Worker 还与 `MAVLINK_SOURCE` 和 `SIMULATION_WORKER_ENABLED` 有联动。

为了避免真机 + 模拟混用，推荐：

```ini
MAVLINK_SOURCE=mavlink
SIMULATION_WORKER_ENABLED=false
```

---

## 11. 真机网络配置

B2 默认常用网段是：

```text
192.168.123.x
```

建议把本机真机网口设置为：

```text
192.168.123.222/24
```

### 11.1 查看网口

```bash
ip link show
```

确认网口名称确实是：

```text
enP3p49s0
```

### 11.2 配置 IP 与 multicast 路由

```bash
sudo ip addr replace 192.168.123.222/24 dev enP3p49s0
sudo ip route replace 224.0.0.0/4 dev enP3p49s0
```

### 11.3 验证

```bash
ip addr show dev enP3p49s0
ip route show | grep 224.0.0.0/4
ping 192.168.123.161
```

如果 `ping 192.168.123.161` 不通，不要继续调项目代码，先解决网络问题。

---

## 12. CycloneDDS 安装

安装 `unitree_sdk2_python` 前，必须先安装底层 C 版 CycloneDDS。

### 12.1 安装依赖

```bash
sudo apt update
sudo apt install -y build-essential cmake git pkg-config
```

### 12.2 下载并编译 CycloneDDS

```bash
cd ~
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x
cd cyclonedds
mkdir -p build install
cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install
cmake --build . --target install -j$(nproc)
```

### 12.3 如果安装时遇到权限错误

如果出现类似：

```text
Permission denied: .../install_manifest.txt
```

说明是目录权限问题，不是编译失败。

处理：

```bash
sudo chown -R orangepi:orangepi ~/cyclonedds
chmod -R u+rwX ~/cyclonedds
cd ~/cyclonedds/build
cmake --build . --target install -j$(nproc)
```

### 12.4 导出环境变量

```bash
export CYCLONEDDS_HOME=$HOME/cyclonedds/install
export CMAKE_PREFIX_PATH=$CYCLONEDDS_HOME:${CMAKE_PREFIX_PATH:-}
export LD_LIBRARY_PATH=$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}
export PKG_CONFIG_PATH=$CYCLONEDDS_HOME/lib/pkgconfig:${PKG_CONFIG_PATH:-}
```

建议把这些加入 `~/.bashrc`，避免每次重开终端都要手动导出。

---

## 13. Python cyclonedds 安装

在虚拟环境里安装：

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install --no-build-isolation cyclonedds==0.10.2
```

### 13.1 关于 setuptools 冲突

如果出现类似：

```text
torch 需要 setuptools<82
```

说明当前环境中 `setuptools` 版本偏高。

建议修复：

```bash
python -m pip install "setuptools<82"
```

然后检查：

```bash
python -m pip show setuptools torch cyclonedds
```

---

## 14. Unitree SDK 安装

### 14.1 克隆 SDK

```bash
cd ~/Code/Project/BOTDOG
git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
```

### 14.2 安装

```bash
export CYCLONEDDS_HOME=$HOME/cyclonedds/install
export CMAKE_PREFIX_PATH=$CYCLONEDDS_HOME:${CMAKE_PREFIX_PATH:-}
export LD_LIBRARY_PATH=$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}
export PKG_CONFIG_PATH=$CYCLONEDDS_HOME/lib/pkgconfig:${PKG_CONFIG_PATH:-}

cd ~/Code/Project/BOTDOG/unitree_sdk2_python
source ../BotDog/.venv/bin/activate
python -m pip install -e .
```

### 14.3 SDK 导入自检

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
python -c "from unitree_sdk2py.core.channel import ChannelFactoryInitialize; print('dds ok')"
python -c "from unitree_sdk2py.b2.sport.sport_client import SportClient; print('sport ok')"
python -c "from unitree_sdk2py.comm.motion_switcher.motion_switcher_client import MotionSwitcherClient; print('motion switcher ok')"
```

只要这三条通过，说明：

- CycloneDDS Python 绑定正常
- Unitree SDK 正常
- B2 控制相关模块可导入

### 14.4 建议先跑 SDK 官方示例

在调 BotDog 前，建议先验证 SDK 自己能连上 B2：

```bash
cd ~/Code/Project/BOTDOG/unitree_sdk2_python
source ../BotDog/.venv/bin/activate
python3 ./example/high_level/read_highstate.py enP3p49s0
```

如果这一步不通，优先排查：

- 网卡名
- IP
- 路由
- CycloneDDS
- SDK

不是先怀疑 BotDog 代码。

---

## 15. 启动真机后端

建议第一次真机联调时，不要直接使用复杂脚本，优先手动启动。

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
PYTHONPATH=. python run_backend.py
```

---

## 16. 真机状态诊断

后端启动后，先不要直接发运动命令。
先检查控制适配器状态：

```bash
curl http://127.0.0.1:8000/api/v1/control/debug
```

理想结果应看到类似：

- `type = UnitreeB2Adapter`
- `initialized = true`
- `sport_client_exists = true`
- `worker_thread_alive = true`

如果看到的仍然是模拟适配器，说明真机适配器还没成功初始化。

---

## 17. 真机首次动作测试建议

第一次真机动作测试，务必保守。

建议顺序：

1. `stand`
2. `stop`
3. 低速 `left/right`
4. 低速 `forward`

示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/control/command \
  -H "Content-Type: application/json" \
  -d '{"cmd":"stand"}'

curl -X POST http://127.0.0.1:8000/api/v1/control/command \
  -H "Content-Type: application/json" \
  -d '{"cmd":"stop"}'
```

> 不建议首次联调就直接高速前进。

---

## 18. YOLO 模型下载与配置

项目 AI 功能需要 YOLO 模型文件。

### 18.1 先安装依赖

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 18.2 下载 YOLO 模型 (推荐 YOLOv8n)

在 OrangePi 等部署版上，推荐体积更小、推理更快的 **`yolov8n.pt`** (Nano 版，约 6MB)；如果是在 PC 上或者对检测精度要求极高，可以选择 **`yolov8s.pt`** (Small 版，约 22MB)。
**注意：两者都完全支持自动跟踪功能，跟踪有无与模型带不带 "n" 或 "s" 无关。**

**下载 YOLOv8n (首选):**
```bash
cd ~/Code/Project/BOTDOG/BotDog
mkdir -p models
wget -O models/yolov8n.pt \
  https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt
```

**或者下载 YOLOv8s (如果需要更高精度):**
```bash
cd ~/Code/Project/BOTDOG/BotDog
mkdir -p models
wget -O models/yolov8s.pt \
  https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s.pt
```

或者使用 `curl`：

```bash
curl -L \
  https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt \
  -o models/yolov8n.pt
```

检查文件是否存在：

```bash
ls -lh models/yolov8*.pt
```

### 18.4 修改 backend/.env

建议显式指定：

```ini
AI_ENABLED=true
AI_MODEL_PATH=models/yolov8n.pt
AI_DEVICE=cpu
```

说明：

- 在 OrangePi 上先用 `cpu` 更稳
- 不要依赖模糊路径，直接指定 `models/yolov8n.pt`

### 18.5 重启后端

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
PYTHONPATH=. python run_backend.py
```

---

## 19. MediaMTX 视频链路安装

项目视频链路依赖：

- `ffmpeg`
- `mediamtx`

你已经确认系统里有 `ffmpeg`，但没有 `mediamtx`。

### 19.1 下载 MediaMTX

官方下载地址：

- 仓库：<https://github.com/bluenviron/mediamtx>
- Releases：<https://github.com/bluenviron/mediamtx/releases>

OrangePi 5 Ultra 一般使用：

- Linux ARM64 版本

先检查架构：

```bash
uname -m
```

如果输出 `aarch64`，通常选择：

```text
linux_arm64
```

### 19.2 安装方式一：放到项目默认位置

项目 Linux 启动脚本默认寻找：

```text
~/Code/Project/BOTDOG/BotDog/scripts/mediamtx
```

所以最简单方式：

```bash
cd ~/Downloads
# 假设你已经下载了 mediamtx_xxx_linux_arm64.tar.gz
tar -xzf mediamtx_*.tar.gz

cd ~/Code/Project/BOTDOG/BotDog
cp ~/Downloads/mediamtx ./scripts/mediamtx
chmod +x ./scripts/mediamtx
```

### 19.3 安装方式二：装到系统路径

```bash
sudo cp /你的解压路径/mediamtx /usr/local/bin/mediamtx
sudo chmod +x /usr/local/bin/mediamtx
```

然后运行脚本前指定：

```bash
export MEDIAMTX_EXE=/usr/local/bin/mediamtx
```

### 19.4 检查是否安装成功

```bash
which mediamtx
mediamtx --version
which ffmpeg
ffmpeg -version
```

### 19.5 替代视频源：使用 USB 摄像头推流

如果由于天空端/局域网限制无法拉取图传视频流，可直接将一个 UVC 免驱 USB 摄像头插在 OrangePi 的 USB 口上：

1. **查看摄像头设备号：**
   ```bash
   ls /dev/video*
   ```
   通常 HDMI 输入为 `/dev/video0`，USB 摄像头会是 `/dev/video1` 或 `/dev/video2`。

2. **使用一键推流脚本：**
   确保 MediaMTX 已经启动，然后运行预备好的脚本：
   ```bash
   ./scripts/start_usb_cam.sh /dev/video1
   ```
   *说明：如果不加 `/dev/video1` 参数，默认也会尝试读 `/dev/video1`。该脚本底层封装着 FFmpeg 命令，并已配置 TCP 传输防闪退。*

3. 后端正常使用 `AI_RTSP_URL=rtsp://127.0.0.1:8554/cam` 拉流即可。前端的 WebRTC (WHEP) 也均可直接通过配置好的 MediaMTX 地址拉到画面。

---

## 20. 启动视频流水线

如果 `mediamtx` 放在项目默认位置：

```bash
cd ~/Code/Project/BOTDOG/BotDog
bash scripts/run-pipeline.sh
```

如果 `mediamtx` 在系统路径：

```bash
cd ~/Code/Project/BOTDOG/BotDog
export MEDIAMTX_EXE=/usr/local/bin/mediamtx
bash scripts/run-pipeline.sh
```

### 20.1 查看日志

```bash
tail -f logs/mediamtx.log
tail -f logs/ffmpeg.log
```

### 20.2 前端视频地址

视频链路正常后，前端可配置：

```ini
VITE_WHEP_URL=http://<OrangePi_IP>:8889/cam/whep
```

如果视频没准备好，也可以先留空，前端其他功能仍可正常使用。

---

## 21. 环境检查建议

项目内有环境检查逻辑，可以帮助确认视频依赖是否齐全：

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
python backend/scripts/validate_environment.py
```

---

## 22. 当前“是否已经达到上真机标准”

### 可以认为已经达到的

- 前后端基本运行正常
- Python 3.12 环境已就绪
- 数据库能初始化
- 模拟模式可运行
- CycloneDDS Python 绑定可安装
- 具备继续接真机的基本条件

### 还不能直接说“所有功能都完全正常”的原因

完整功能还包含：

- B2 真机控制
- B2 真机遥测
- AI 检测
- 视频链路
- 自动跟踪
- 告警联动

只有在这些都实测通过后，才能说“所有功能正常运行”。

### 建议的真机最小验收清单

1. SDK 导入通过
2. SDK 官方示例能读取 B2 状态
3. `control/debug` 显示 `UnitreeB2Adapter initialized=true`
4. 前端收到真实遥测
5. `stand`、`stop` 成功
6. YOLO 模型能加载
7. 视频链路能出流

---

## 23. 常见错误与处理

### 23.1 `pip: command not found`

处理：

```bash
python3.12 -m ensurepip --upgrade
python3.12 -m pip --version
```

### 23.2 `ModuleNotFoundError: No module named 'backend'`

原因：项目脚本导入路径问题。

处理：

```bash
PYTHONPATH=. python scripts/init_db.py
PYTHONPATH=. python run_backend.py
```

### 23.3 `sqlite3.OperationalError: unable to open database file`

原因：`data/` 目录不存在或无权限。

处理：

```bash
mkdir -p data
chmod u+rwx data
sudo chown -R orangepi:orangepi data
```

### 23.4 `vite: not found`

原因：前端依赖未安装。

处理：

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

### 23.5 `Could not locate cyclonedds`

原因：只装了 Python 包，没装底层 CycloneDDS C 库。

处理：

1. 编译安装 `cyclonedds`
2. 导出 `CYCLONEDDS_HOME`
3. 再安装 `cyclonedds==0.10.2`
4. 再安装 `unitree_sdk2_python`

### 23.6 `Permission denied: install_manifest.txt`

原因：`~/cyclonedds` 部分目录权限异常。

处理：

```bash
sudo chown -R orangepi:orangepi ~/cyclonedds
chmod -R u+rwX ~/cyclonedds
cd ~/cyclonedds/build
cmake --build . --target install -j$(nproc)
```

### 23.7 `MediaMTX not found`

原因：系统有 `ffmpeg`，但没有 `mediamtx`。

处理：

- 下载 Linux ARM64 版 MediaMTX
- 放到 `scripts/mediamtx`
- 或设置 `MEDIAMTX_EXE=/usr/local/bin/mediamtx`

### 23.8 `DDS_RETCODE_PRECONDITION_NOT_MET` — DDS Topic 创建失败

**现象：** 后端启动时报：

```
cyclonedds.core.DDSException: [DDS_RETCODE_PRECONDITION_NOT_MET]
Occurred upon initialisation of a cyclonedds.topic.Topic
```

`ChannelFactoryInitialize` 成功，但 `ChannelSubscriber` 或 `SportClient.Init()` 失败。

**原因：** pip 安装的 `cyclonedds==0.10.2` 内置了一个对 arm64 有 bug 的 C 库，必须改用手动编译的版本。

**解决：** 启动后端前设置以下环境变量，指向自己编译的 CycloneDDS：

```bash
export CYCLONEDDS_HOME=$HOME/cyclonedds/install
export LD_LIBRARY_PATH=$CYCLONEDDS_HOME/lib:${LD_LIBRARY_PATH:-}
```

建议加入 `~/.bashrc` 永久生效。如果还没编译：

```bash
cd ~
git clone https://github.com/eclipse-cyclonedds/cyclonedds -b releases/0.10.x
cd cyclonedds && mkdir -p build install && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=../install
cmake --build . --target install -j$(nproc)
```



## 24. 推荐的最终联调顺序

推荐严格按下面顺序推进：

### 阶段 A：基础环境

1. 安装 Python 3.12
2. 建虚拟环境
3. 安装后端依赖
4. 初始化数据库
5. 启动后端
6. 启动前端

### 阶段 B：模拟模式

1. `MAVLINK_SOURCE=simulation`
2. `SIMULATION_WORKER_ENABLED=true`
3. 页面看到遥测
4. 数据库写入正常

### 阶段 C：真机基础

1. 配置 `backend/.env`
2. 配置 `enP3p49s0`
3. 配置 IP 和 multicast 路由
4. 安装 CycloneDDS
5. 安装 `cyclonedds==0.10.2`
6. 安装 `unitree_sdk2_python`
7. 运行 SDK 示例

### 阶段 D：真机联调

1. 启动后端
2. 检查 `/api/v1/control/debug`
3. 检查前端遥测
4. 先 `stand`
5. 再 `stop`
6. 最后小速度转向和前进

### 阶段 E：高级功能

1. 下载 YOLO 模型
2. 启用 AI Worker
3. 安装 MediaMTX
4. 启动视频链路
5. 联调自动跟踪与事件系统

---

## 25. 推荐长期保留的命令速查表

### 进入项目环境

```bash
cd ~/Code/Project/BOTDOG/BotDog
source .venv/bin/activate
```

### 初始化数据库

```bash
PYTHONPATH=. python scripts/init_db.py
```

### 启动后端

```bash
PYTHONPATH=. python run_backend.py
```

### 启动前端

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

### 检查控制适配器

```bash
curl http://127.0.0.1:8000/api/v1/control/debug
```

### 真机网口配置

```bash
sudo ip addr replace 192.168.123.222/24 dev enP3p49s0
sudo ip route replace 224.0.0.0/4 dev enP3p49s0
```

### 下载 YOLO 模型 (推荐 YOLOv8n)

体积更小、速度更快（约 6MB），适用于 OrangePi：
```bash
mkdir -p models
wget -O models/yolov8n.pt \
  https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.pt
```

如果需要更高精度（约 22MB）：
```bash
wget -O models/yolov8s.pt \
  https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s.pt
```

### 启动视频流水线

```bash
bash scripts/run-pipeline.sh
```

---

## 26. 最后的建议

1. 不要跳步骤，先模拟、后真机。
2. 先确保 SDK 官方示例可用，再调 BotDog 真机控制。
3. 真机初次动作一定保守，先 `stand` / `stop`。
4. AI 和视频不要和真机控制同时第一次联调，建议分阶段。
5. 对 OrangePi 这类开发板，尽量保持：
   - Python 环境稳定
   - `.venv` 固定
   - `CYCLONEDDS_HOME` 固定
   - `backend/.env` 明确配置

---

## 27. 当前结论

基于本次实际部署与排障过程，可以得出：

- 你已经基本具备继续推进真机联调的条件
- 但只有在 `Unitree SDK + 真实遥测 + 控制 debug + stand/stop + YOLO + 视频链路` 全部完成验证后，才能说“所有功能都正常运行”

推荐下一步优先级：

1. 完成 `unitree_sdk2_python` 安装与示例验证
2. 确认 `/api/v1/control/debug` 为真机适配器
3. 完成 `stand/stop` 首次真机测试
4. 下载 YOLO 模型并验证 AI Worker
5. 安装 MediaMTX 并跑通视频链路
