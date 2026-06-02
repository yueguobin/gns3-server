# Rootless Docker 安装与配置（GNS3 服务器）

## 概述

Rootless Docker 允许以非 root 用户运行 Docker 守护进程，消除对 `privileged` 容器的依赖，提升安全性。GNS3 服务器在 rootless 模式下无需设置 `UsernsMode: host`，也不需要在容器内执行权限修复（`_fix_permissions` 为空操作）。

## 适用系统

- Debian (bookworm 及更新版本)
- Ubuntu 22.04+
- 其他 Linux 发行版（需 systemd 支持）
- openSUSE Tumbleweed（使用 `docker-rootless` 包）

## 安装步骤

### 1. 卸载旧版 Docker（如有）

```bash
# 如果之前通过系统包管理器安装过
sudo apt remove docker.io docker-ce docker-ce-cli containerd.io
```

### 2. 安装 Docker CE（含 rootless 支持）

```bash
# 使用官方安装脚本
curl -fsSL https://get.docker.com | sh
```

该脚本会自动安装 `docker-ce-rootless-extras` 包。

### 3. 安装 uidmap 依赖（rootless 必需）

```bash
sudo apt-get install -y uidmap
```

### 4. 停用 rootful Docker 服务

```bash
sudo systemctl stop docker.service docker.socket
sudo systemctl disable docker.service docker.socket
sudo rm -f /var/run/docker.sock
```

### 5. 安装 rootless Docker

```bash
dockerd-rootless-setuptool.sh install
```

安装程序会自动：
- 创建 systemd 用户服务 `~/.config/systemd/user/docker.service`
- 启用并启动 docker 服务
- 创建 Docker CLI context `rootless` 并设为当前 context
- 安装 slirp4netns 网络驱动

### 6. 配置环境变量

```bash
# 将 DOCKER_HOST 添加到 ~/.bashrc
echo 'export DOCKER_HOST=unix:///run/user/1000/docker.sock' >> ~/.bashrc
source ~/.bashrc
```

### 7. 启用用户 linger（开机自启）

```bash
sudo loginctl enable-linger <用户名>
```

## 验证

```bash
# 查看 rootless Docker 状态
systemctl --user status docker

# 确认 rootless 模式
docker info 2>&1 | grep -i rootless

# 测试容器运行
docker run hello-world
```

## 生命周期管理

```bash
# 启动/停止/重启
systemctl --user start docker.service
systemctl --user stop docker.service
systemctl --user restart docker.service

# 查看日志
journalctl --user -u docker.service -f
```

## GNS3 适配说明

Rootless 模式下 GNS3 服务器的变更：

| 配置项 | Rootful | Rootless |
|--------|---------|----------|
| 容器特权模式 | `Privileged: True` | `Privileged: False` |
| 用户命名空间 | `UsernsMode: "host"` | 取消设置（由 rootless 自动管理） |
| 权限修复 | `_fix_permissions` 执行 chown/chmod | 空操作（容器内无 root 权限） |

## 注意事项

- Rootless 模式不支持下列 Docker 功能：`SYS_ADMIN` 能力、非特权端口绑定（<1024）、某些存储驱动（如 devicemapper）
- 网络使用 slirp4netns 或 pasta，性能略低于 bridge 模式
- 如果端口映射需要，可以使用 `docker context use rootless` 切换上下文
- 如遇到权限问题，确保 `~/.docker/` 目录权限正确
