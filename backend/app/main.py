from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_graph import router as graph_router
from app.api.routes_query import router as query_router
from app.config.constants import APP_NAME, APP_VERSION
from app.config.settings import get_settings
from app.utils.logger import setup_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger = setup_logger(settings.log_level)
    logger.info("Starting %s v%s", APP_NAME, APP_VERSION)
    yield
    logger.info("Shutting down %s", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(graph_router)
app.include_router(query_router)


@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}
