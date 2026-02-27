from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .routers import jobs, admin, payment

@asynccontextmanager
async def lifespan(app: FastAPI):
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
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Anonymous-Id"],
)
app.include_router(jobs.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(payment.router, prefix="/api")

@app.get("/health")
def health():
    return {"status": "ok"}
