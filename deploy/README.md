# Ubuntu 系统服务部署指南

本目录包含在 Ubuntu 服务器上部署 AI 乒乓球教练应用的 systemd 服务配置文件和脚本。

## 文件说明

- `pingpong-backend.service` - 后端 API 服务的 systemd 配置
- `pingpong-frontend.service` - 前端 Web 服务的 systemd 配置
- `install.sh` - 一键部署安装脚本
- `manage.sh` - 服务管理脚本（启动/停止/重启/查看日志）

## 快速部署

### 1. 自动部署（推荐）

```bash
# 1. 进入项目根目录
cd /path/to/agent-skill-lib

# 2. 运行安装脚本（需要 sudo 权限）
sudo ./deploy/install.sh

# 3. 启动服务
sudo ./deploy/manage.sh start

# 4. 查看服务状态
sudo ./deploy/manage.sh status
```

### 2. 手动部署

```bash
# 1. 创建安装目录
sudo mkdir -p /opt/agent-skill-lib

# 2. 复制项目文件
sudo cp -r backend /opt/agent-skill-lib/
sudo cp -r frontend /opt/agent-skill-lib/

# 3. 安装后端依赖
cd /opt/agent-skill-lib/backend
sudo python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 4. 安装前端依赖
cd /opt/agent-skill-lib/frontend
npm install

# 5. 配置环境变量
sudo nano /opt/agent-skill-lib/backend/.env
# 添加: ZHIPU_API_KEY=your_api_key_here

# 6. 安装 systemd 服务
sudo cp deploy/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pingpong-backend pingpong-frontend

# 7. 启动服务
sudo systemctl start pingpong-backend pingpong-frontend
```

## 服务管理

### 使用管理脚本（推荐）

```bash
# 启动所有服务
./deploy/manage.sh start

# 停止所有服务
./deploy/manage.sh stop

# 重启所有服务
./deploy/manage.sh restart

# 查看服务状态
./deploy/manage.sh status

# 查看日志（实时）
./deploy/manage.sh logs

# 只管理后端服务
./deploy/manage.sh restart backend

# 只管理前端服务
./deploy/manage.sh restart frontend

# 查看特定服务日志
./deploy/manage.sh logs backend
```

### 使用 systemctl 命令

```bash
# 启动服务
sudo systemctl start pingpong-backend
sudo systemctl start pingpong-frontend

# 停止服务
sudo systemctl stop pingpong-backend
sudo systemctl stop pingpong-frontend

# 重启服务
sudo systemctl restart pingpong-backend
sudo systemctl restart pingpong-frontend

# 查看服务状态
sudo systemctl status pingpong-backend
sudo systemctl status pingpong-frontend

# 查看日志
sudo journalctl -u pingpong-backend -f
sudo journalctl -u pingpong-frontend -f

# 开机自启
sudo systemctl enable pingpong-backend
sudo systemctl enable pingpong-frontend
```

## 配置防火墙

如果启用了 UFW 防火墙，需要开放端口：

```bash
sudo ufw allow 5173/tcp  # 前端端口
sudo ufw allow 8000/tcp  # 后端 API 端口
sudo ufw reload
```

## 环境变量配置

### 后端 (.env)

```bash
# 智谱 AI API Key（必需，用于真实分析）
ZHIPU_API_KEY=your_api_key_here

# 分析模式（mock=模拟数据, real=调用 AI）
AGENT_MODE=mock
```

### 前端 (.env)

```bash
# 后端 API 地址
VITE_API_URL=http://192.168.0.3:8000
```

将 `192.168.0.3` 替换为服务器的实际 IP 地址。

## 故障排查

### 服务无法启动

```bash
# 查看服务状态和错误信息
sudo systemctl status pingpong-backend
sudo journalctl -u pingpong-backend -n 50
```

### 常见问题

1. **端口被占用**
   ```bash
   # 检查端口占用
   sudo lsof -i :8000
   sudo lsof -i :5173
   ```

2. **权限问题**
   ```bash
   # 修改文件所有者
   sudo chown -R www-data:www-data /opt/agent-skill-lib
   ```

3. **Python 依赖问题**
   ```bash
   # 重新安装依赖
   cd /opt/agent-skill-lib/backend
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **前端 API 连接失败**
   - 检查 `frontend/.env` 中的 `VITE_API_URL` 是否正确
   - 确保后端服务正在运行
   - 检查防火墙设置

## 卸载

```bash
# 停止并禁用服务
sudo systemctl stop pingpong-backend pingpong-frontend
sudo systemctl disable pingpong-backend pingpong-frontend

# 删除服务文件
sudo rm /etc/systemd/system/pingpong-*.service
sudo systemctl daemon-reload

# 删除项目文件（可选）
sudo rm -rf /opt/agent-skill-lib
```

## 系统要求

- Ubuntu 20.04 或更高版本
- Python 3.11+
- Node.js 18+
- 至少 2GB RAM
- 至少 10GB 磁盘空间
