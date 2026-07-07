# Windows 一键启动脚本 (PowerShell)
# 
# 1. 中间件 (PostgreSQL / Redis) 通过 Docker 启动
# 2. 后端 (FastAPI) 运行在 5177 端口
# 3. 前端 (Vite) 运行在 5170 端口
# 4. Celery Worker (使用 -P solo 兼容 Windows)

$ErrorActionPreference = "Stop"

# 项目根目录
$PROJECT_ROOT = $PSScriptRoot
if ([string]::IsNullOrEmpty($PROJECT_ROOT)) {
    $PROJECT_ROOT = Get-Location
}

# 端口配置
$REDIS_PORT = 6380
$POSTGRES_PORT = 5433
$BACKEND_PORT = 5177
$FRONTEND_PORT = 5170

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  AI Viral Content Matrix System 启动工具" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. 检查 Docker 是否运行
Write-Host "[1/4] 检查 Docker 守护进程..." -ForegroundColor Yellow
& docker info >$null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] Docker 尚未启动，请先打开 Docker Desktop 软件，然后再运行此脚本。" -ForegroundColor Red
    Exit 1
}
Write-Host "Docker 守护进程运行正常。" -ForegroundColor Green

# 2. 启动中间件 (PostgreSQL & Redis)
Write-Host "[2/4] 启动中间件 (Docker Compose)..." -ForegroundColor Yellow
cd $PROJECT_ROOT
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 启动 Docker 容器失败。" -ForegroundColor Red
    Exit 1
}

# 等待数据库就绪
Write-Host "等待 PostgreSQL & Redis 就绪..." -ForegroundColor Yellow
$pg_ready = $false
for ($i=1; $i -le 15; $i++) {
    & docker exec aiviral-postgres pg_isready -U helloworld >$null 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pg_ready = $true
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $pg_ready) {
    Write-Host "[警告] PostgreSQL 在 15 秒内未就绪，将尝试继续..." -ForegroundColor Yellow
} else {
    Write-Host "中间件服务已就绪！" -ForegroundColor Green
}

# 3. 检查并配置后端虚拟环境
Write-Host "[3/4] 检查后端 Python 虚拟环境..." -ForegroundColor Yellow
$BACKEND_DIR = Join-Path $PROJECT_ROOT "backend"
$VENV_DIR = Join-Path $BACKEND_DIR ".venv"

if (-not (Test-Path $VENV_DIR)) {
    Write-Host "未检测到 Python 虚拟环境，正在创建并安装依赖..." -ForegroundColor Yellow
    cd $BACKEND_DIR
    python -m venv .venv
    Write-Host "虚拟环境创建成功。" -ForegroundColor Green
}

# 确保安装依赖
Write-Host "正在检查后端依赖包..." -ForegroundColor Yellow
cd $BACKEND_DIR
& .venv\Scripts\pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "[错误] 安装后端依赖失败。" -ForegroundColor Red
    Exit 1
}
Write-Host "后端依赖检查完成。" -ForegroundColor Green

# 4. 检查前端依赖
Write-Host "[4/4] 检查前端 Node 依赖包..." -ForegroundColor Yellow
$FRONTEND_DIR = Join-Path $PROJECT_ROOT "frontend"
if (-not (Test-Path (Join-Path $FRONTEND_DIR "node_modules"))) {
    Write-Host "未检测到前端 node_modules，正在执行 npm install..." -ForegroundColor Yellow
    cd $FRONTEND_DIR
    npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[错误] 前端依赖安装失败。" -ForegroundColor Red
        Exit 1
    }
}
Write-Host "前端依赖检查完成。" -ForegroundColor Green

Write-Host "`n启动各个服务窗口..." -ForegroundColor Cyan

# 定义环境变量并启动后端 FastAPI
$BackendCmd = "`$Host.UI.RawUI.WindowTitle='AIViral - FastAPI 后端'; cd '$BACKEND_DIR'; `$env:DATABASE_URL='postgresql+asyncpg://helloworld@localhost:$POSTGRES_PORT/aiviral'; `$env:CELERY_BROKER_URL='redis://localhost:$REDIS_PORT/0'; `$env:CELERY_RESULT_BACKEND='redis://localhost:$REDIS_PORT/0'; .venv\Scripts\uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT --reload"
Start-Process PowerShell -ArgumentList "-NoExit", "-Command", $BackendCmd

# 启动 Celery Worker
# 注：Windows 下 celery 必须指定 -P solo 或 eventlet 才能正常消费任务
$CeleryCmd = "`$Host.UI.RawUI.WindowTitle='AIViral - Celery 任务队列'; cd '$BACKEND_DIR'; `$env:DATABASE_URL='postgresql+asyncpg://helloworld@localhost:$POSTGRES_PORT/aiviral'; `$env:CELERY_BROKER_URL='redis://localhost:$REDIS_PORT/0'; `$env:CELERY_RESULT_BACKEND='redis://localhost:$REDIS_PORT/0'; .venv\Scripts\celery -A app.celery_app worker --loglevel=info -P solo"
Start-Process PowerShell -ArgumentList "-NoExit", "-Command", $CeleryCmd

# 启动前端
$FrontendCmd = "`$Host.UI.RawUI.WindowTitle='AIViral - Vite 前端'; cd '$FRONTEND_DIR'; npm run dev -- --port $FRONTEND_PORT --host"
Start-Process PowerShell -ArgumentList "-NoExit", "-Command", $FrontendCmd

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "  启动指令已成功发送！" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host "- 前端界面:   http://localhost:$FRONTEND_PORT" -ForegroundColor Yellow
Write-Host "- 后端 API:   http://localhost:$BACKEND_PORT/docs" -ForegroundColor Yellow
Write-Host "- PostgreSQL: localhost:$POSTGRES_PORT (helloworld)" -ForegroundColor Yellow
Write-Host "- Redis:      localhost:$REDIS_PORT" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Green
Write-Host "提示：请查看弹出的三个控制台窗口。如要关闭服务，直接关闭对应控制台窗口，并在 Docker Desktop 中停止容器即可。`n" -ForegroundColor Gray
