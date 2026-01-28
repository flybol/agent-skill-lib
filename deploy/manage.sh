#!/bin/bash
# AI 乒乓球教练 - 服务管理脚本
# 使用方法: ./manage.sh [start|stop|restart|status|logs]

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

BACKEND_SERVICE="pingpong-backend"
FRONTEND_SERVICE="pingpong-frontend"

# 显示帮助信息
show_help() {
    echo "AI 乒乓球教练 - 服务管理脚本"
    echo ""
    echo "使用方法:"
    echo "  ./manage.sh [命令]"
    echo ""
    echo "可用命令:"
    echo "  start    - 启动所有服务"
    echo "  stop     - 停止所有服务"
    echo "  restart  - 重启所有服务"
    echo "  status   - 查看服务状态"
    echo "  logs     - 查看服务日志"
    echo "  backend  - 只管理后端服务"
    echo "  frontend - 只管理前端服务"
    echo ""
    echo "示例:"
    echo "  ./manage.sh start           # 启动所有服务"
    echo "  ./manage.sh restart backend # 重启后端服务"
    echo "  ./manage.sh logs frontend   # 查看前端日志"
    echo ""
}

# 启动服务
start_services() {
    local services=()
    if [[ "$1" == "backend" ]] || [[ -z "$1" ]]; then
        services+=("$BACKEND_SERVICE")
    fi
    if [[ "$1" == "frontend" ]] || [[ -z "$1" ]]; then
        services+=("$FRONTEND_SERVICE")
    fi

    echo -e "${YELLOW}启动服务...${NC}"
    for service in "${services[@]}"; do
        echo -n "  启动 $service... "
        systemctl start "$service.service" 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
    done
    echo ""
}

# 停止服务
stop_services() {
    local services=()
    if [[ "$1" == "backend" ]] || [[ -z "$1" ]]; then
        services+=("$BACKEND_SERVICE")
    fi
    if [[ "$1" == "frontend" ]] || [[ -z "$1" ]]; then
        services+=("$FRONTEND_SERVICE")
    fi

    echo -e "${YELLOW}停止服务...${NC}"
    for service in "${services[@]}"; do
        echo -n "  停止 $service... "
        systemctl stop "$service.service" 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
    done
    echo ""
}

# 重启服务
restart_services() {
    local services=()
    if [[ "$1" == "backend" ]] || [[ -z "$1" ]]; then
        services+=("$BACKEND_SERVICE")
    fi
    if [[ "$1" == "frontend" ]] || [[ -z "$1" ]]; then
        services+=("$FRONTEND_SERVICE")
    fi

    echo -e "${YELLOW}重启服务...${NC}"
    for service in "${services[@]}"; do
        echo -n "  重启 $service... "
        systemctl restart "$service.service" 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${RED}✗${NC}"
    done
    echo ""
}

# 查看服务状态
show_status() {
    echo -e "${BLUE}=== 服务状态 ===${NC}"
    echo ""

    echo -e "${YELLOW}后端服务 (${BACKEND_SERVICE}):${NC}"
    systemctl status "$BACKEND_SERVICE.service" --no-pager -l || true
    echo ""

    echo -e "${YELLOW}前端服务 (${FRONTEND_SERVICE}):${NC}"
    systemctl status "$FRONTEND_SERVICE.service" --no-pager -l || true
    echo ""

    # 显示访问地址
    local ip=$(hostname -I | awk '{print $1}')
    echo -e "${BLUE}=== 访问地址 ===${NC}"
    echo "  前端:     http://$ip:5173"
    echo "  后端API:  http://$ip:8000"
    echo ""
}

# 查看日志
show_logs() {
    local service="$1"

    if [[ "$service" == "backend" ]]; then
        journalctl -u "$BACKEND_SERVICE.service" -f
    elif [[ "$service" == "frontend" ]]; then
        journalctl -u "$FRONTEND_SERVICE.service" -f
    else
        echo "同时查看两个服务的日志（按 Ctrl+C 退出）："
        echo ""
        journalctl -u "$BACKEND_SERVICE.service" -u "$FRONTEND_SERVICE.service" -f
    fi
}

# 主逻辑
case "$1" in
    start)
        start_services "$2"
        ;;
    stop)
        stop_services "$2"
        ;;
    restart)
        restart_services "$2"
        ;;
    status)
        show_status
        ;;
    logs)
        show_logs "$2"
        ;;
    backend|frontend)
        # 允许 ./manage.sh backend 作为 ./manage.sh start backend 的简写
        start_services "$1"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${RED}错误: 未知命令 '$1'${NC}"
        echo ""
        show_help
        exit 1
        ;;
esac
