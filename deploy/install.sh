#!/bin/bash
# AI 乒乓球教练 - Ubuntu 部署脚本
# 使用方法: sudo ./install.sh

set -e

echo "=========================================="
echo "  AI 乒乓球教练 - 系统服务部署脚本"
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否以 root 权限运行
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}错误: 请使用 sudo 运行此脚本${NC}"
    exit 1
fi

# 配置变量
INSTALL_DIR="/opt/agent-skill-lib"
PROJECT_DIR="$(pwd)"
BACKEND_SERVICE="pingpong-backend.service"
FRONTEND_SERVICE="pingpong-frontend.service"

# 步骤 1: 检查依赖
echo -e "${YELLOW}[1/7] 检查系统依赖...${NC}"
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 Python 3${NC}"; exit 1; }
command -v node >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 Node.js${NC}"; exit 1; }
command -v npm >/dev/null 2>&1 || { echo -e "${RED}错误: 未安装 npm${NC}"; exit 1; }

# 检查并安装 uv（Python 包管理器）
if ! command -v uv >/dev/null 2>&1; then
    echo -e "${YELLOW}  安装 uv 包管理器...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    echo -e "${GREEN}  ✓ uv 安装完成${NC}"
else
    echo -e "${GREEN}  ✓ uv 已安装${NC}"
fi

echo -e "${GREEN}✓ 系统依赖检查通过${NC}"
echo ""

# 步骤 2: 创建目录
echo -e "${YELLOW}[2/7] 创建安装目录...${NC}"
mkdir -p "$INSTALL_DIR"
echo -e "${GREEN}✓ 目录创建完成: $INSTALL_DIR${NC}"
echo ""

# 步骤 3: 复制项目文件
echo -e "${YELLOW}[3/7] 复制项目文件...${NC}"
cp -r "$PROJECT_DIR/backend" "$INSTALL_DIR/"
cp -r "$PROJECT_DIR/frontend" "$INSTALL_DIR/"
echo -e "${GREEN}✓ 项目文件复制完成${NC}"
echo ""

# 步骤 4: 安装后端依赖
echo -e "${YELLOW}[4/7] 安装后端 Python 依赖（使用 uv）...${NC}"
cd "$INSTALL_DIR/backend"

# 使用 uv 创建虚拟环境并安装依赖
uv venv
source venv/bin/activate
uv pip install -r requirements.txt
echo -e "${GREEN}✓ 后端依赖安装完成${NC}"
echo ""

# 步骤 5: 安装前端依赖
echo -e "${YELLOW}[5/7] 安装前端 Node.js 依赖...${NC}"
cd "$INSTALL_DIR/frontend"
npm install
echo -e "${GREEN}✓ 前端依赖安装完成${NC}"
echo ""

# 步骤 6: 配置环境变量
echo -e "${YELLOW}[6/7] 配置环境变量...${NC}"
# 检查后端 .env 文件
if [ ! -f "$INSTALL_DIR/backend/.env" ]; then
    echo -e "${YELLOW}  创建后端 .env 示例文件${NC}"
    cat > "$INSTALL_DIR/backend/.env" << EOF
# 智谱 AI API Key（必需，用于真实分析）
ZHIPU_API_KEY=your_api_key_here

# 分析模式（mock=模拟数据, real=调用 AI）
AGENT_MODE=mock
EOF
    echo -e "${YELLOW}  ⚠ 请编辑 $INSTALL_DIR/backend/.env 并添加 ZHIPU_API_KEY${NC}"
fi

# 配置前端环境变量
sed -i "s|VITE_API_URL=.*|VITE_API_URL=http://$(hostname -I | awk '{print $1}'):8000|" "$INSTALL_DIR/frontend/.env"
echo -e "${GREEN}✓ 前端 API 地址已配置为: http://$(hostname -I | awk '{print $1}'):8000${NC}"
echo ""

# 步骤 7: 安装系统服务
echo -e "${YELLOW}[7/7] 安装系统服务...${NC}"
cp "$PROJECT_DIR/deploy/$BACKEND_SERVICE" /etc/systemd/system/
cp "$PROJECT_DIR/deploy/$FRONTEND_SERVICE" /etc/systemd/system/

# 重新加载 systemd
systemctl daemon-reload

# 启用服务
systemctl enable pingpong-backend.service
systemctl enable pingpong-frontend.service

echo -e "${GREEN}✓ 系统服务安装完成${NC}"
echo ""

# 完成信息
echo "=========================================="
echo -e "${GREEN}  部署完成！${NC}"
echo "=========================================="
echo ""
echo "服务管理命令："
echo "  启动服务:   sudo systemctl start pingpong-backend pingpong-frontend"
echo "  停止服务:   sudo systemctl stop pingpong-backend pingpong-frontend"
echo "  重启服务:   sudo systemctl restart pingpong-backend pingpong-frontend"
echo "  查看状态:   sudo systemctl status pingpong-backend pingpong-frontend"
echo "  查看日志:   sudo journalctl -u pingpong-backend -f"
echo "              sudo journalctl -u pingpong-frontend -f"
echo ""
echo "访问地址："
echo "  前端:       http://$(hostname -I | awk '{print $1}'):5173"
echo "  后端 API:   http://$(hostname -I | awk '{print $1}'):8000"
echo ""
echo -e "${YELLOW}⚠ 重要提示：${NC}"
echo "1. 请编辑 $INSTALL_DIR/backend/.env 添加智谱 API Key"
echo "2. 确保防火墙允许端口 5173 和 8000："
echo "   sudo ufw allow 5173"
echo "   sudo ufw allow 8000"
echo ""
