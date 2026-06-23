from __future__ import annotations

from pathlib import Path
from re import split

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Tự đọc biến môi trường từ `.env` và bỏ qua key thừa để dễ cấu hình local.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Thông tin chạy API.
    app_name: str = Field(default="VinSmart Audio Pipeline", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")

    # Kết nối database.
    postgres_host: str = Field(default="localhost", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="audio_pipeline", alias="POSTGRES_DB")
    postgres_user: str = Field(default="postgres", alias="POSTGRES_USER")
    postgres_password: str = Field(default="postgres", alias="POSTGRES_PASSWORD")
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # Các thư mục dữ liệu mà pipeline sẽ đọc/ghi.
    storage_root: Path = Field(default=Path("data"), alias="STORAGE_ROOT")
    raw_youtube_dir: Path = Field(default=Path("data/raw/youtube"), alias="RAW_YOUTUBE_DIR")
    processed_audio_dir: Path = Field(default=Path("data/processed/audio"), alias="PROCESSED_AUDIO_DIR")
    metadata_dir: Path = Field(default=Path("data/metadata"), alias="METADATA_DIR")
    log_dir: Path = Field(default=Path("logs"), alias="LOG_DIR")

    # Guard rail cho crawl de giam nguy co bi YouTube rate limit/block.
    crawl_min_delay_sec: float = Field(default=2.0, alias="CRAWL_MIN_DELAY_SEC")
    crawl_max_delay_sec: float = Field(default=8.0, alias="CRAWL_MAX_DELAY_SEC")
    crawl_job_cooldown_sec: float = Field(default=5.0, alias="CRAWL_JOB_COOLDOWN_SEC")
    crawl_block_cooldown_sec: float = Field(default=900.0, alias="CRAWL_BLOCK_COOLDOWN_SEC")
    crawl_url_retry_limit: int = Field(default=2, alias="CRAWL_URL_RETRY_LIMIT")
    yt_dlp_cookie_file: str = Field(default="", alias="YT_DLP_COOKIE_FILE")
    yt_dlp_cookie_backup_file: str = Field(default="", alias="YT_DLP_COOKIE_BACKUP_FILE")
    yt_dlp_proxy_backups: str = Field(default="", alias="YT_DLP_PROXY_BACKUPS")
    ingest_urls_per_job: int = Field(default=50, alias="INGEST_URLS_PER_JOB")
    discovery_enabled: bool = Field(default=False, alias="DISCOVERY_ENABLED")
    discovery_batch_size: int = Field(default=20, alias="DISCOVERY_BATCH_SIZE")
    discovery_cycle_limit_per_start: int = Field(default=0, alias="DISCOVERY_CYCLE_LIMIT_PER_START")
    discovery_min_delay_sec: float = Field(default=5.0, alias="DISCOVERY_MIN_DELAY_SEC")
    discovery_max_delay_sec: float = Field(default=10.0, alias="DISCOVERY_MAX_DELAY_SEC")
    discovery_topic_file: str = Field(default="topic.txt", alias="DISCOVERY_TOPIC_FILE")
    discovery_query_window_size: int = Field(default=20, alias="DISCOVERY_QUERY_WINDOW_SIZE")
    discovery_search_queries: str = Field(
        default="tin tuc viet nam;am nhac viet nam;phong su viet nam;podcast tieng viet",
        alias="DISCOVERY_SEARCH_QUERIES",
    )

    # Cấu hình tracing để theo dõi pipeline khi cần debug.
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="audio-pipeline", alias="LANGSMITH_PROJECT")
    langchain_api_key: str = Field(default="", alias="LANGCHAIN_API_KEY")

    # Cấu hình bot Telegram để bắn log khi cần.
    telegram_log_enabled: bool = Field(default=False, alias="TELEGRAM_LOG_ENABLED")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    resume_incomplete_jobs_on_startup: bool = Field(
        default=False,
        alias="RESUME_INCOMPLETE_JOBS_ON_STARTUP",
    )

    # Cấu hình segment-level pipeline (VAD ONNX nội bộ + cắt câu + ASR fallback).
    vad_model_path: Path = Field(default=Path("../VAD/models/vad/1/vad.onnx"), alias="VAD_MODEL_PATH")
    vad_threshold: float = Field(default=0.7, alias="VAD_THRESHOLD")
    vad_min_volume: float = Field(default=0.6, alias="VAD_MIN_VOLUME")
    vad_start_secs: float = Field(default=0.1, alias="VAD_START_SECS")
    vad_stop_secs: float = Field(default=0.6, alias="VAD_STOP_SECS")
    vad_chunk_ms: int = Field(default=64, alias="VAD_CHUNK_MS")
    segments_dir: Path = Field(default=Path("data/processed/segments"), alias="SEGMENTS_DIR")
    sentence_max_sec: float = Field(default=8.0, alias="SENTENCE_MAX_SEC")
    sentence_min_sec: float = Field(default=0.3, alias="SENTENCE_MIN_SEC")
    phrase_gap_sec: float = Field(default=0.45, alias="PHRASE_GAP_SEC")
    use_vtt_transcript: bool = Field(default=True, alias="USE_VTT_TRANSCRIPT")
    segment_pad_sec: float = Field(default=0.35, alias="SEGMENT_PAD_SEC")
    segment_min_sec: float = Field(default=0.3, alias="SEGMENT_MIN_SEC")
    segment_boundary_slack_sec: float = Field(default=0.8, alias="SEGMENT_BOUNDARY_SLACK_SEC")
    segment_merge_gap_sec: float = Field(default=0.5, alias="SEGMENT_MERGE_GAP_SEC")
    vtt_overlap_sec: float = Field(default=0.2, alias="VTT_OVERLAP_SEC")
    # Chuẩn hóa âm lượng (EBU R128 loudnorm) khi normalize audio, không chỉ đổi format.
    loudnorm_enabled: bool = Field(default=True, alias="LOUDNORM_ENABLED")
    loudnorm_i: float = Field(default=-16.0, alias="LOUDNORM_I")
    loudnorm_tp: float = Field(default=-1.5, alias="LOUDNORM_TP")
    loudnorm_lra: float = Field(default=11.0, alias="LOUDNORM_LRA")
    quality_gate_enabled: bool = Field(default=True, alias="QUALITY_GATE_ENABLED")
    quality_gate_min_rms: float = Field(default=0.015, alias="QUALITY_GATE_MIN_RMS")
    quality_gate_min_peak: float = Field(default=0.05, alias="QUALITY_GATE_MIN_PEAK")
    quality_gate_min_active_ratio: float = Field(default=0.35, alias="QUALITY_GATE_MIN_ACTIVE_RATIO")
    quality_gate_chunk_ms: int = Field(default=200, alias="QUALITY_GATE_CHUNK_MS")
    quality_gate_min_tokens_per_sec: float = Field(default=0.6, alias="QUALITY_GATE_MIN_TOKENS_PER_SEC")
    quality_gate_max_tokens_per_sec: float = Field(default=6.0, alias="QUALITY_GATE_MAX_TOKENS_PER_SEC")
    quality_gate_long_segment_sec: float = Field(default=2.5, alias="QUALITY_GATE_LONG_SEGMENT_SEC")
    quality_gate_min_tokens_for_long_segment: int = Field(
        default=2,
        alias="QUALITY_GATE_MIN_TOKENS_FOR_LONG_SEGMENT",
    )
    asr_model: str = Field(default="large-v3", alias="ASR_MODEL")
    asr_device: str = Field(default="cuda", alias="ASR_DEVICE")
    asr_beam_size: int = Field(default=5, alias="ASR_BEAM_SIZE")
    # ASR hardening chống ảo giác khoảng lặng (xem FasterWhisperAdapter / text_quality).
    asr_no_speech_threshold: float = Field(default=0.6, alias="ASR_NO_SPEECH_THRESHOLD")
    asr_logprob_min: float = Field(default=-1.0, alias="ASR_LOGPROB_MIN")
    asr_vad_filter: bool = Field(default=True, alias="ASR_VAD_FILTER")
    # WER gate: ASR (hypothesis) vs VTT (reference) mức segment để QA alignment.
    # Tắt mặc định (ASR mỗi segment rất nặng); bật để flag segment lệch caption.
    wer_gate_enabled: bool = Field(default=False, alias="WER_GATE_ENABLED")
    wer_gate_max: float = Field(default=0.05, alias="WER_GATE_MAX")
    # Video nhạc over-flag (whisper base dở giọng hát) -> bỏ gate cho title nhạc.
    wer_gate_skip_music: bool = Field(default=True, alias="WER_GATE_SKIP_MUSIC")
    # Keyword bổ sung (CSV) ngoài default; rỗng = chỉ dùng default. Vd "grey d,mck".
    wer_gate_music_keywords: str = Field(default="", alias="WER_GATE_MUSIC_KEYWORDS")
    # LLM sửa hypothesis ASR (chính tả/đồng âm VN) trước khi so VTT -> WER đúng hơn.
    # Tắt mặc định; bật cần Ollama chạy ở URL dưới. Fail-open nếu LLM lỗi.
    wer_gate_llm_judge_enabled: bool = Field(default=False, alias="WER_GATE_LLM_JUDGE_ENABLED")
    wer_gate_llm_judge_url: str = Field(default="http://localhost:11434", alias="WER_GATE_LLM_JUDGE_URL")
    wer_gate_llm_judge_model: str = Field(default="qwen2.5:7b", alias="WER_GATE_LLM_JUDGE_MODEL")
    wer_gate_llm_judge_timeout: float = Field(default=30.0, alias="WER_GATE_LLM_JUDGE_TIMEOUT")

    # Tách vocal bằng Demucs trước normalize (chạy trên raw, giữ chất lượng tách).
    # Tắt mặc định -> pipeline giữ nguyên hành vi cũ. Command trỏ env riêng có torch.
    demucs_enabled: bool = Field(default=True, alias="DEMUCS_ENABLED")
    demucs_mode: str = Field(default="auto", alias="DEMUCS_MODE")
    demucs_command: str = Field(default="python -m demucs", alias="DEMUCS_COMMAND")
    demucs_model: str = Field(default="htdemucs", alias="DEMUCS_MODEL")
    demucs_device: str = Field(default="cuda", alias="DEMUCS_DEVICE")
    separated_audio_dir: Path = Field(default=Path("data/processed/separated"), alias="DEMUCS_SEPARATED_DIR")
    # auto mode: noise floor (dB) của raw >= ngưỡng -> file nhiễu -> Demucs; thấp hơn -> ffmpeg.
    # -50 dB là điểm khởi đầu (tune để ~20% rơi vào Demucs trên data thực).
    demucs_noise_floor_db: float = Field(default=-50.0, alias="DEMUCS_NOISE_FLOOR_DB")

    @property
    def resolved_database_url(self) -> str:
        # Ưu tiên DATABASE_URL nếu được truyền sẵn, còn không thì tự ghép từ từng biến nhỏ.
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def resolved_yt_dlp_cookie_file(self) -> Path | None:
        cleaned = self.yt_dlp_cookie_file.strip()
        return Path(cleaned) if cleaned else None

    @property
    def resolved_yt_dlp_cookie_backup_file(self) -> Path | None:
        cleaned = self.yt_dlp_cookie_backup_file.strip()
        return Path(cleaned) if cleaned else None

    @property
    def resolved_yt_dlp_proxy_backups(self) -> list[str]:
        raw_value = self.yt_dlp_proxy_backups.strip()
        if not raw_value:
            return []
        return [item.strip() for item in split(r"[\n,;]+", raw_value) if item.strip()]

    @property
    def resolved_discovery_search_queries(self) -> list[str]:
        raw_value = self.discovery_search_queries.strip()
        if not raw_value:
            return []
        return [item.strip() for item in split(r"[\n;]+", raw_value) if item.strip()]

    @property
    def resolved_discovery_topic_file(self) -> Path | None:
        cleaned = self.discovery_topic_file.strip()
        return Path(cleaned) if cleaned else None

    @property
    def resolved_discovery_cursor_file(self) -> Path:
        return self.storage_root / "discovery" / "topic_cursor.json"

    @property
    def resolved_demucs_mode(self) -> str:
        if not self.demucs_enabled:
            return "off"
        mode = self.demucs_mode.strip().lower()
        return mode if mode in {"off", "on", "auto"} else "auto"


# Tạo singleton settings để mọi nơi trong app dùng cùng một cấu hình.
settings = Settings()
