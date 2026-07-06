"""AIViralContentMatrixSystem - FastAPI 主入口"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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


@app.get("/api/health")
async def health():
    return {"status": "ok", "app": settings.app_name}
