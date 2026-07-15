#!/bin/bash
#
# AIViralContentMatrixSystem 本地一键启动脚本
# 中间件 (Redis / PostgreSQL) 通过 Docker 启动 (使用非默认端口)
# 后端 (FastAPI) 启动在 5177 端口
# 前端 (Vite) 启动在 5170 端口
#
set -euo pipefail

# ============================================================
# 配置区
# ============================================================
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

# 中间件 (Docker)
REDIS_PORT=6380
POSTGRES_PORT=5433

# 后端
BACKEND_PORT=5177
BACKEND_DIR="$PROJECT_ROOT/backend"

# 前端
FRONTEND_PORT=5170
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# Celery
CELERY_WORKER_CONCURRENCY=2
ENABLE_CELERY_BEAT=false  # 设为 true 可启用定时采集调度

# ============================================================
# 颜色
# ============================================================
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }
title() { echo -e "\n${CYAN}===== $1 =====${NC}"; }

# ============================================================
# 清理函数 (Ctrl+C 时调用)
# ============================================================
cleanup() {
    echo ""
    warn "收到退出信号，正在清理..."
    # 停止后台进程 (Celery + 后端 + 前端)
    if [ -n "${CELERY_PID:-}" ]; then
        kill "$CELERY_PID" 2>/dev/null || true
    fi
    if [ -n "${CELERY_BEAT_PID:-}" ]; then
        kill "$CELERY_BEAT_PID" 2>/dev/null || true
    fi
    if [ -n "${BACKEND_PID:-}" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "${FRONTEND_PID:-}" ]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    # 停止 Docker 容器
    info "停止 Docker Compose 服务..."
    docker compose -f "$PROJECT_ROOT/docker-compose.yml" down 2>/dev/null || true
    info "清理完成"
    exit 0
}
trap cleanup SIGINT SIGTERM

# ============================================================
# 前置检查
# ============================================================
title "前置检查"

# 检查必要命令
for cmd in docker lsof uv npm; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        error "未找到 $cmd，请先安装"
        exit 1
    fi
done
info "必要命令均已安装"

PYTHON_VERSION="$(cat "$PROJECT_ROOT/.python-version")"
VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

# 检查 Docker daemon 是否可用
if ! docker info >/dev/null 2>&1; then
    error "Docker daemon 不可用，请确保 Docker Desktop 已启动"
    exit 1
fi
info "Docker daemon 可用"

# ============================================================
# 清理残留容器（如果之前异常退出）
# ============================================================
title "清理残留容器"
docker compose -f "$PROJECT_ROOT/docker-compose.yml" down --remove-orphans 2>/dev/null || true
info "残留容器已清理"

# 端口检查函数（仅检查非中间件端口）
check_port() {
    local port=$1
    local name=$2
    if lsof -i :"$port" >/dev/null 2>&1; then
        error "端口 $port ($name) 已被占用，请先释放"
        exit 1
    fi
    info "端口 $port ($name) 可用"
}

check_port $BACKEND_PORT  "后端"
check_port $FRONTEND_PORT "前端"

# ============================================================
# 启动中间件 (Docker)
# ============================================================
title "启动中间件 (Docker Compose)"

# 使用 docker compose 启动 Redis + PostgreSQL
docker compose -f "$PROJECT_ROOT/docker-compose.yml" up -d

# 等待 PostgreSQL 就绪
info "等待 PostgreSQL 就绪..."
for i in $(seq 1 30); do
    if docker exec aiviral-postgres pg_isready -U helloworld >/dev/null 2>&1; then
        info "PostgreSQL 就绪"
        break
    fi
    if [ "$i" -eq 30 ]; then
        error "PostgreSQL 启动超时"
        exit 1
    fi
    sleep 1
done

# 等待 Redis 就绪
info "等待 Redis 就绪..."
for i in $(seq 1 15); do
    if docker exec aiviral-redis redis-cli ping 2>/dev/null | grep -q "PONG"; then
        info "Redis 就绪"
        break
    fi
    if [ "$i" -eq 15 ]; then
        error "Redis 启动超时"
        exit 1
    fi
    sleep 1
done

# ============================================================
# 环境变量 (覆盖默认端口)
# ============================================================
title "设置环境变量"

export DATABASE_URL="postgresql+asyncpg://helloworld@localhost:$POSTGRES_PORT/aiviral"
export CELERY_BROKER_URL="redis://localhost:$REDIS_PORT/0"
export CELERY_RESULT_BACKEND="redis://localhost:$REDIS_PORT/0"

info "DATABASE_URL=$DATABASE_URL"
info "CELERY_BROKER_URL=$CELERY_BROKER_URL"

# ============================================================
# 启动后端
# ============================================================
title "启动后端 (端口 $BACKEND_PORT)"

cd "$PROJECT_ROOT"

info "同步 Python 虚拟环境 (uv, Python $PYTHON_VERSION)..."
uv sync --python "$PYTHON_VERSION"

if [ ! -x "$PYTHON_BIN" ]; then
    error "未找到项目虚拟环境解释器: $PYTHON_BIN"
    exit 1
fi

ACTUAL_PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')"
if [ "$ACTUAL_PYTHON_VERSION" != "$PYTHON_VERSION" ]; then
    error "Python 版本不匹配: 期望 $PYTHON_VERSION，实际 $ACTUAL_PYTHON_VERSION"
    exit 1
fi
info "Python 运行时: $("$PYTHON_BIN" --version)"

cd "$BACKEND_DIR"

"$PYTHON_BIN" -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload &
BACKEND_PID=$!
info "后端已启动 (PID: $BACKEND_PID)"

# 等待后端就绪
info "等待后端就绪..."
for i in $(seq 1 30); do
    if curl -s "http://localhost:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
        info "后端就绪"
        break
    fi
    if [ "$i" -eq 30 ]; then
        error "后端启动超时"
        exit 1
    fi
    sleep 1
done

# ============================================================
# 启动 Celery Worker
# ============================================================
title "启动 Celery Worker"

cd "$BACKEND_DIR"

"$PYTHON_BIN" -m celery -A app.celery_app worker \
    --loglevel=info \
    --concurrency="$CELERY_WORKER_CONCURRENCY" \
    -n worker1@%%h &
CELERY_PID=$!
info "Celery Worker 已启动 (PID: $CELERY_PID, concurrency=$CELERY_WORKER_CONCURRENCY)"

# 可选：启动 Celery Beat 定时调度
if [ "$ENABLE_CELERY_BEAT" = "true" ]; then
    "$PYTHON_BIN" -m celery -A app.celery_app beat --loglevel=info &
    CELERY_BEAT_PID=$!
    info "Celery Beat 定时调度已启动 (PID: $CELERY_BEAT_PID)"
else
    info "Celery Beat 定时调度未启用 (ENABLE_CELERY_BEAT=false)"
fi

# ============================================================
# 启动前端
# ============================================================
title "启动前端 (端口 $FRONTEND_PORT)"

cd "$FRONTEND_DIR"

# 确保依赖已安装
if [ ! -d "node_modules" ]; then
    info "安装前端依赖..."
    npm install
fi

npx vite --port "$FRONTEND_PORT" --host &
FRONTEND_PID=$!
info "前端已启动 (PID: $FRONTEND_PID)"

# 等待前端就绪
sleep 3
if lsof -i :"$FRONTEND_PORT" >/dev/null 2>&1; then
    info "前端就绪"
else
    warn "前端可能尚未完全就绪，请稍候检查"
fi

# ============================================================
# 启动摘要
# ============================================================
title "启动完成 🎉"
echo ""
info "中间件:"
info "  Redis:       localhost:$REDIS_PORT"
info "  PostgreSQL:  localhost:$POSTGRES_PORT"
echo ""
info "后端:        http://localhost:$BACKEND_PORT"
info "  API 文档:   http://localhost:$BACKEND_PORT/docs"
echo ""
info "前端:        http://localhost:$FRONTEND_PORT"
echo ""
info "Celery:"
info "  Worker:     PID $CELERY_PID (concurrency=$CELERY_WORKER_CONCURRENCY)"
if [ "$ENABLE_CELERY_BEAT" = "true" ]; then
    info "  Beat:       PID $CELERY_BEAT_PID (定时调度已启用)"
fi
echo ""
info "按 Ctrl+C 停止所有服务"
echo ""

# 保持脚本运行，等待退出信号
wait
