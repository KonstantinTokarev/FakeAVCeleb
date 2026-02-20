from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routers import jobs, admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    from .config import settings
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    await init_db()
    yield
    # shutdown

app = FastAPI(
    title="Deepfake Detector API",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

@app.get("/health")
def health():
    return {"status": "ok"}
