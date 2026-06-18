from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


# Engine dùng chung cho toàn backend.
engine = create_engine(settings.resolved_database_url, future=True)
# Session factory để tạo transaction cho từng request hoặc background job.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    # Dependency cho FastAPI: mở session khi vào request và luôn đóng khi kết thúc.
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
