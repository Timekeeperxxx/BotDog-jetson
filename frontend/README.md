# BotDog 前端

BotDog 前端是基于 React、TypeScript 和 Vite 的控制终端，包含登录页、主控台、导航巡逻页面和管理后台。当前实现已不是早期“阶段 1”原型，文档以当前源码为准。

## 技术栈

| 组件 | 说明 |
|------|------|
| React | 19.x |
| TypeScript | 5.9.x |
| Vite | 7.x，多入口构建 |
| Three.js | PCD 点云 3D 预览 |
| Zustand | 登录态与部分全局状态 |
| Vitest | 单元测试 |

## 入口页面

| 路径 | 入口 | 说明 |
|------|------|------|
| `/login` | `src/pages/LoginPage.tsx` | 登录页 |
| `/` | `src/IndustrialConsoleComplete.tsx` | 主控制台，含视频、遥测、手动控制、AI/驱离、证据 |
| `/admin` | `src/admin/AdminApp.tsx` | 管理后台 |
| `/nav-patrol.html` | `src/pages/PcdMapDemoPage.tsx` | PCD 场景、导航点、巡逻任务和 ROS2 重定位 |

## 开发命令

```bash
cd frontend
npm install
npm run dev
npm run build
npm run lint
npm run test
```

开发服务器默认端口为 `5174`。`vite.config.ts` 会把 `/api` 和 `/ws` 代理到 `VITE_API_BASE_URL`，未设置时使用 `http://127.0.0.1:8000`。

## 关键环境变量

| 变量 | 说明 |
|------|------|
| `VITE_API_BASE_URL` | 后端 HTTP 地址，例如 `http://192.168.144.104:8000` |
| `VITE_WHEP_URL` | 主视频 WHEP 地址；未设置时按当前 hostname 生成 `http://<host>:8889/cam/whep` |

## 目录结构

```text
src/
├── AppRoot.tsx                 # 登录、主控台、管理后台路由分发
├── IndustrialConsoleComplete.tsx # 主控制台容器
├── nav-patrol-main.tsx         # 导航巡逻独立入口
├── admin/                      # 管理后台页面、布局和 API 封装
├── api/                        # 前端 API 客户端
├── components/                 # 控制台组件、视频、证据、PCD 组件
├── hooks/                      # WebSocket、WHEP、导航、控制、证据等 hooks
├── pages/                      # 登录、证据历史、PCD 导航页
├── stores/                     # authStore 等全局状态
├── types/                      # DTO 与 UI 类型
└── utils/                      # 坐标变换、手柄、导航点校验等工具
```

## 功能范围

- 登录鉴权与 token 自动附加。
- 主控制台 WHEP 视频、遥测 WebSocket、事件 WebSocket、手动控制和急停。
- AI 自动跟踪、驱离模式、抓拍、录像和证据历史。
- PCD 点云 2D/3D 预览、导航点管理、巡逻任务、建图状态、重定位 ready 判定。
- 管理后台：系统总览、导航、设备与视频、日志、配置、用户权限等。
