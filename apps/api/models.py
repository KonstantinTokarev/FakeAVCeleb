from sqlalchemy import Column, String, DateTime, Enum, ForeignKey, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.sql import func
from uuid import uuid4
import uuid

from .database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    status = Column(String(32), nullable=False, default="CREATED")
    input_type = Column(String(16), nullable=False)  # link | upload
    input_url = Column(Text, nullable=True)
    input_filename = Column(String(255), nullable=True)
    options = Column(JSON, nullable=True)  # {max_seconds, single_face}
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    artifacts = Column(JSON, nullable=True)  # storage paths
    result_id = Column(String(36), ForeignKey("results.id"), nullable=True)
    progress_step = Column(String(32), nullable=True)
    progress_done = Column(String(8), nullable=True)
    progress_total = Column(String(8), nullable=True)


class Result(Base):
    __tablename__ = "results"

    id = Column(String(36), primary_key=True, default=gen_uuid)
    job_id = Column(String(36), nullable=False)  # FK to jobs.id
    score_overall = Column(String(24), nullable=False)
    confidence = Column(String(16), nullable=False)
    segments = Column(JSON, nullable=False)
    signals = Column(JSON, nullable=False)
    model_meta = Column(JSON, nullable=False)
    # Extended report fields
    verdict = Column(String(32), nullable=True)
    sub_scores = Column(JSON, nullable=True)
    findings = Column(JSON, nullable=True)
    flagged_frames = Column(JSON, nullable=True)
