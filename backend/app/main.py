"""AIViralContentMatrixSystem - FastAPI 主入口"""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.api import content, assets, articles, domains


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init database
    await init_db()
    yield
    # Shutdown
    pass


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(content.router)
app.include_router(assets.router)
app.include_router(articles.router)
app.include_router(domains.router)

# Mount static files folder
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
