# 北京本地开发环境

工作区：`/home/frank/Projects/beijing`。两个仓库保留独立 Git 历史，均使用
`dev/beijing-docker-2204` 分支。本目录属于 BotDog-jetson，工作区 `docker` 是指向本目录的符号链接。

## 当前部署

- 容器 `beijing-dev`，镜像 `beijing-dev:humble-2204`。
- Ubuntu 22.04.5、amd64、ROS2 Humble、Python 3.10.12，CPU PyTorch；前端通过 Node 22 容器构建。
- BotDog：<http://127.0.0.1:8002>；Navigation 测试页面：<http://127.0.0.1:8092>。
- 管理员 `admin`；随机初始密码保存在 `../../backend/.env` 的 `AUTH_ADMIN_PASSWORD`，该文件未纳入 Git。
- 模型只读挂载到 `/workspace/models`，来源 `/home/frank/Projects/Models`。
- 雷达 `192.168.123.188`；当前接收主机 `192.168.123.11`，网卡 `enx6c1ff763dc8b`。
- 云台 `192.168.123.100:2332`；视频源 `rtsp://192.168.123.100:554/`。
- 独立视频端口：RTSP 8556、WHEP 8891、ICE/UDP 8191，绑定本机回环地址。
- ROS_DOMAIN_ID=51、ROS_LOCALHOST_ONLY=1；容器使用 host 网络支持同机 ROS 和雷达 UDP。
- 底盘使用 simulation，模拟遥测数据关闭，自动跟踪/驱离关闭；启动后端会按上游行为切云台到可见光模式。

## 日常使用

以下命令在工作区根目录运行。当前用户若无 Docker socket 权限，可使用 `sudo docker`。

```bash
# 停止/重新启动整个环境（不删除源码、模型或数据库）
docker stop beijing-dev
docker start beijing-dev

# 进入已加载 ROS 与导航包的开发 shell
docker exec -it beijing-dev /usr/local/bin/beijing-env bash
# 后端 Python：/opt/venv/bin/python；ROS/colcon 使用系统 Python。

# 重新编译导航（完成后重启容器加载新 install）
docker exec beijing-dev /usr/local/bin/beijing-env bash /workspace/project/docker/build-navigation.sh

# 验证部署：HTTP、ROS 包、真实视频、CPU 模型推理和分支保护
docker exec beijing-dev /usr/local/bin/beijing-env /opt/venv/bin/python /workspace/project/docker/verify.py

# 日志位于 docker/backend.log、video.log、navigation-test.log
```

没有自动启动建图/定位或真机运动。地图根目录为工作区 `MAPS`，Navigation/maps 链接到同一目录，当前无用户地图。
测试页面可以按需启动建图；实机导航需先提供/创建地图并完成雷达外参和定位验证。
现有挂载/倾角来自上游配置，不代表已在当前安装位置重新标定。
若连接远端 Jetson ROS，应将 ROS 域与其对齐、设 ROS_LOCALHOST_ONLY=0，并核实 VPN/局域网 DDS 路由；仅有 IP 不代表跨网 DDS 可达。

## 重建本机容器

```bash
docker build -t beijing-dev:humble-2204 docker
# 仅在容器不存在时执行；已有容器用 docker start。
bash docker/start.sh
```

Dockerfile 复用本机已经安装的 `botdog-dev-66671b4ca1:humble`
（本次检查镜像 ID 前缀 `20d9d86d3495`），它含 ROS、PCL、Livox SDK2、CPU AI 依赖和 amd64 MediaMTX。
这不是公开镜像：迁移其他电脑时需导出/导入该基础镜像，或依据本机
`/home/frank/Projects/TailiBotDog/docker/dev/Dockerfile` 及其依赖文件重新构建。
此次未重新执行整套基础镜像安装，但已核验系统版本、pip check 并用当前源码重新编译。

前端重新构建：

```bash
docker run --rm --network host --user "$(id -u):$(id -g)" \
  -e npm_config_cache=/tmp/npm-cache \
  -e VITE_WHEP_URL=http://127.0.0.1:8891/cam/whep \
  --mount "type=bind,src=$PWD/BotDog-jetson/frontend,dst=/app" \
  -w /app node:22-bookworm sh -c 'npm ci --no-audit --no-fund && npm run build'
```

新工作区首次配置可从 `backend.env.example` 复制到 `BotDog-jetson/backend/.env`，
替换两处 CHANGE_ME 为不同随机值。容器使用 UID/GID 1000，其他用户应调整用户与目录权限。
当前数据库已经将 cam1 设置为 8891/8556，未连接的视频源已禁用。
新数据库的上游默认视频端口仍是 8889/8554，需在后台“视频源”中设置 cam1 的
WHEP URL 为 `http://127.0.0.1:8891/cam/whep`、RTSP 为 `rtsp://127.0.0.1:8556/cam`，禁用其余未连接来源。

## ARM 与模型边界

从 Jetson 上传源码不要求本机使用 ARM。当前 C++/ROS 包在 amd64 重新编译，Python/前端使用本机原生依赖。
仓库自带 `scripts/mediamtx` 实际是 AArch64 ELF，本部署使用镜像中的 amd64 同版本程序。
上游视频脚本使用 Jetson `gst-nvenc`，本部署直接转发相机 H.264，不启动其相机自动重启恢复脚本。

- helmet.pt、yolo11n-pose.pt 用于本地 CPU；人脸使用两份 ONNX。
- 武器检测只有 TensorRT engine，缺少可移植源模型，本机默认关闭。
- 天气分类已启用，使用 checkpoint-3000 和 CPU；已通过本地测试图片推理。
- 姿态、人脸、安全帽及持续识别均已启用，配置已同步到数据库和 backend/.env。
- TensorRT engine 受平台、GPU 和 TensorRT 构建条件限制，应在目标 Jetson 重新生成/验证。
- Jetson 真机 GPU 部署需要 ARM64 和匹配的 JetPack/L4T/CUDA/TensorRT。尚未获取目标 Jetson 的确切版本；此容器不构成真机 GPU 兼容性验收。
- 上游 README 写 Python 3.12，但本次后端在 Jammy 原生 Python 3.10 实际启动；这不等于全仓库路径均已验证。

参考：<https://docs.nvidia.com/deeplearning/tensorrt/latest/getting-started/support-matrix.html>

## 分支约束

两仓库的本地 `core.hooksPath` 指向本目录 `hooks`，拒绝更新/删除 main 和 master。
这是本地保护，不等同 GitHub 服务端规则；其他克隆需重新安装，不要用 `--no-verify` 绕过。

```bash
for repo in Navigation BotDog-jetson; do
  git -C "$repo" config core.hooksPath "$PWD/BotDog-jetson/docker/beijing/hooks"
  git -C "$repo" config push.default current
done
# 用户要求推送时，先检查分支、diff 和待推送提交，然后显式指定：
# git push -u origin HEAD:refs/heads/dev/beijing-docker-2204
```

## 本次源码兼容修正

建图、视频 PID 文件和录包路径改为根据实际仓库位置/已有环境变量解析，消除 Jetson 用户目录硬编码。

## 验证记录

源版本：Navigation `dbce6ba9d860c65a70b5dede1f48b31f093262b9`；BotDog-jetson `9f6a90cacd8b280f2bd62eb44625d66d93433be2`。

- 前端 `npm ci && npm run build` 通过；Python `pip check` 通过。
- 初始管理员登录通过；BotDog 和 Navigation 测试页面返回 HTTP 200。
- 两个设备各 2 次 ping 均通过；相机及独立 MediaMTX 的 ffprobe 均返回 H.264 1280x720。
- 路径相关既有测试 21 通过、1 失败。失败项 `test_start_mapping_wrapper_waits_for_unified_runtime_readiness`
  静态检查 Navigation 脚本中的旧字符串 `wait_for_livox_data`，当前上游脚本已不含它；
  被检查的测试及 Navigation 脚本均未在此次修改。详见 `path-tests.log`。
- 真实定位、规划、避障和机器人运动尚未验收；未连接 Jetson 执行部署或改动其系统。
- Navigation 全部 15 包编译通过，耗时 9 分 55 秒；7 个包有上游编译警告，无失败包。
- 重建并启动最终容器后，`verify.py` 全部通过：系统版本、分支保护、HTTP、ROS 包、
  真实视频帧、CPU 安全帽/姿态推理以及两个人脸模型加载。
- 交互式 bash 的 ROS/日志路径检查通过。验证日志：`verification.log`、`navigation-build.log`。

最新启用检查：姿态与天气启动日志均为模型就绪；武器 engine 独立加载失败，仍禁用，需提供兼容的 PT/ONNX 源模型。当前相机 RTSP 返回 EOF/超时，实时识别等待视频恢复；天气离线图片推理通过。
