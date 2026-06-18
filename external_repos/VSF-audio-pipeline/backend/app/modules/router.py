from fastapi import APIRouter

from app.modules.audio_pipeline.api.routes import router as audio_pipeline_router
from app.modules.health.api.routes import router as health_router

# Router version 1 gom toàn bộ module public của backend.
v1_router = APIRouter()
v1_router.include_router(health_router, tags=["health"])
v1_router.include_router(audio_pipeline_router, prefix="/audio-pipeline", tags=["audio-pipeline"])

# Router gốc thêm prefix version để sau này mở rộng v2 dễ hơn.
router = APIRouter()
router.include_router(v1_router, prefix="/api/v1")
