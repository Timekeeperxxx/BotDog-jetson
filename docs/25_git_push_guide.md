# Git 推送和身份验证指南

## 🔐 远程仓库信息

**仓库地址**: `https://github.com/Timekeeperxxx/BotDog.git`
**当前分支**: `main`
**最新提交**: `94ef495 - feat: 添加游戏手柄控制和前端配置界面`

---

## 问题分析

### 错误信息
```bash
fatal: could not read Username for 'https://github.com': No such device or address
fatal: could not read Username for 'https://github.com': No such device or address
```

### 可能原因

1. **GitHub 未配置 Git 凭据**
   - HTTPS 推送需要 Personal Access Token (PAT)
   - 或 SSH 密钥已配置但未在环境变量中

2. **凭证过期**
   - PAT 已过期
   - SSH 密钥权限已撤销

3. **网络问题**
   - 无法访问 GitHub
   - 代理或防火墙阻止

---

## 解决方案

### 方案 1: 使用 Personal Access Token（推荐）

#### 步骤 1: 创建 GitHub PAT

1. 登录 GitHub (https://github.com)
2. 点击右上角头像 → Settings
3. 左侧菜单 → Developer settings
4. 点击 "Personal access tokens" → "Tokens (classic)"
5. 点击 "Generate new token (classic)"
6. 配置 PAT：
   - **Note**: 输入说明，如 "BotDog frontend development"
   - **Expiration**: 选择 "No expiration" 或设置有效时间
   - **Scopes**: 勾选 `repo` (完整访问权限)
   - 点击 "Generate token"
7. **重要**: 复制生成的 token（只显示一次）

#### 步骤 2: 配置 Git 使用 PAT

```bash
# 使用 PAT 推送
git remote set-url origin https://<YOUR_PAT>@github.com/Timekeeperxxx/BotDog.git

# 验证配置
git remote -v

# 现在可以推送了
git push origin main
```

#### 步骤 3: 推送代码

```bash
git push origin main
```

#### 优点
✅ 配置简单
✅ 不需要管理 SSH 密钥
✅ 适合自动化部署

#### 缺点
⚠️ Token 在命令历史中可见（安全性考虑）
⚠️ Token 泄露风险
⚠️ Token 过期需要重新配置

---

### 方案 2: 使用 SSH 密钥（更安全）

#### 步骤 1: 生成 SSH 密钥

**在本地机器**（macOS/Linux）:
```bash
# 生成 SSH 密钥对
ssh-keygen -t rsa -b 4096 -C "your_email@example.com" -f ~/.ssh/github_key
```

**在 Windows**:
```bash
# 使用 PuTTYgen 或 Git Bash
ssh-keygen -t rsa -b 4096 -C "your_email@example.com"
```

#### 步骤 2: 添加公钥到 GitHub

1. 复制公钥内容（`~/.ssh/github_key.pub`）
2. 访问 https://github.com/settings/keys
3. 点击 "New SSH key"
4. 粘贴公钥内容
5. 设置 Title（如 "BotDog Development Machine"）
6. 点击 "Add SSH key"

#### 步骤 3: 配置 Git 使用 SSH

```bash
# 设置远程仓库使用 SSH
git remote set-url origin git@github.com:Timekeeperxxx/BotDog.git

# 验证配置
git remote -v

# 现在可以推送了
git push origin main
```

#### 步骤 4: 配置 SSH 配置文件

创建或编辑 `~/.ssh/config`：
```
Host github.com
    HostName github.com
    IdentityFile ~/.ssh/github_key
    User git
```

#### 优点
✅ 更安全（无 Token）
✅ 无需管理密码
✅ 适合长期使用

#### 缺点
⚠️ 需要管理 SSH 密钥
⚠️ 配置稍微复杂

---

### 方案 3: 使用 GitHub CLI（现代化）

#### 步骤 1: 安装 GitHub CLI

```bash
# macOS (使用 Homebrew)
brew install gh

# Linux
sudo apt-get install gh

# Windows
# 从 https://cli.github.com/ 下载
```

#### 步骤 2: 登录

```bash
gh auth login
```

#### 步骤 3: 推送

```bash
gh repo set-default Timekeeperxxx/BotDog
git push origin main
```

#### 优点
✅ 更现代的用户体验
✅ 支持双因素认证
✅ 更好的安全性

---

## 常用 Git 配置命令

### 查看当前配置

```bash
# 查看所有远程仓库
git remote -v

# 查看远程仓库 URL
git config --get remote.origin.url

# 查看用户名和邮箱
git config user.name
git config user.email
```

### 清理和重置配置

```bash
# 清除错误的远程配置
git remote remove origin

# 移除存储的密码
git config --unset credential.helper
git config --local --unset credential.helper

# 重新配置
git remote add origin https://github.com/Timekeeperxxx/BotDog.git
```

### 修改历史提交（如果需要）

```bash
# 修改最近一次提交的作者信息
git commit --amend --author="Your Name <your@email.com>"

# 修改提交时间
git commit --amend --date="2026-03-06 14:00:00"
```

---

## 故障排查

### 问题 1: 权限被拒绝

**症状**:
```
remote: Permission denied (publickey)
fatal: could not read Username
```

**原因**:
- 仓库是私有的，但你没有权限
- PAT 无效或已过期
- SSH 密钥未添加到账户

**解决**:
- 联系仓库所有者确认权限
- 更新 PAT 或重新添加 SSH 密钥

### 问题 2: 网络连接问题

**症状**:
```
fatal: unable to access 'https://github.com'
```

**解决**:
```bash
# 测试网络连接
curl -I https://github.com

# 使用代理（如果有）
git config --global http.proxy http://proxy.example.com:8080

# 切换到 HTTPS（如果有代理）
git config --global http.sslVerify false
```

### 问题 3: 本地和远程不同步

**症状**:
```
error: failed to push some refs
```

**解决**:
```bash
# 先拉取远程更新
git pull origin main --rebase

# 如果有冲突，解决冲突
git rebase origin/main

# 重新推送
git push origin main
```

---

## 推送后的验证

### 验证推送成功

```bash
# 查看远程分支
git branch -r

# 确认最新提交
git log origin/main --oneline -1
```

### 在 GitHub 上验证

1. 访问 https://github.com/Timekeeperxxx/BotDog
2. 检查最近提交是否包含你的新代码
3. 查看文件列表确认新文件已上传
4. 验证提交历史完整性

---

## 安全最佳实践

### 1. Token 管理

- ✅ 不要将 Token 硬编码到脚本中
- ✅ 使用环境变量存储 Token
- ✅ 定期轮换 Token（每 90 天）
- ✅ 使用最小权限（只选 `repo`）
- ✅ 不要在公开代码仓库中提交 Token

### 2. 敏感信息保护

- ✅ 配置 `.gitignore` 文件
- ✅ 不要提交敏感配置（`.env`、密钥文件）
- ✅ 提交前检查 `git status`，确认不包含敏感信息

### 3. 提交信息规范

- ✅ 使用清晰的提交信息格式
- ✅ 在提交说明中引用相关 Issue 或 PR
- ✅ 保持提交历史清晰可追踪

### 4. 分支管理

- ✅ 主分支保持稳定（`main` 或 `master`）
- ✅ 功能分支使用描述性命名（`feature/gamepad-control`）
- ✅ 及时合并分支，保持仓库清洁

---

## 自动化推送（可选）

### 使用 GitHub Actions 自动推送

创建 `.github/workflows/auto-push.yml`:

```yaml
name: Auto Push
on:
  push:
    branches: [ main ]
  workflow_dispatch:
    inputs:
      branch:
        description: 'Branch to push'
        required: true
        type: string

jobs:
  push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
          repository: Timekeeperxxx/BotDog.git
          branch: ${{ inputs.branch }}
```

**优点**:
- CI/CD 集成
- 自动化测试
- 远程推送无需本地环境

---

## 总结

### 推荐方案

**简单快速**: 方案 1（PAT）- 适合开发和临时使用
**长期稳定**: 方案 2（SSH）- 适合生产环境
**现代体验**: 方案 3（GitHub CLI）- 推荐新项目

### 验收检查清单

推送到远程后，确认以下事项：

- [ ] 代码成功推送到 GitHub
- [ ] 所有新文件已上传
- [ ] 提交历史完整
- [ ] 分支状态正常
- [ ] 功能分支已合并（如果有）

---

## 联系信息

如果遇到持续问题，请联系：

- **GitHub Issues**: https://github.com/Timekeeperxxx/BotDog/issues
- **仓库所有者**: Timekeeperxxx
- **Git 文档**: https://git-scm.com/docs/git-config.html

---

**文档版本**: 1.0
**创建日期**: 2026-03-06
**最后更新**: 2026-03-06
