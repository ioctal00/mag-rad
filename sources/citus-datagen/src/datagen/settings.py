from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_env_files() -> None:
    preset_path = ROOT_DIR / ".env.development"
    local_path = ROOT_DIR / ".env"

    if preset_path.exists():
        load_dotenv(preset_path, override=False)
    if local_path.exists():
        load_dotenv(local_path, override=True)


_load_env_files()


def _resolve_path(value: str) -> str:
    if not value:
        return ""
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    return str((ROOT_DIR / candidate).resolve())


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True, slots=True)
class DatagenSettings:
    postgres_host: str
    postgres_port: int
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_ssl_mode: str
    postgres_ssl_root_cert: str
    datagen_region: str
    datagen_tenant_start: int
    datagen_tenant_end: int
    datagen_tenant_ranges: str
    datagen_event_id_mode: str
    datagen_output_dir: str
    datagen_random_seed: int
    datagen_events_per_tenant: int
    datagen_users_per_tenant: int
    datagen_global_users_per_tenant: int
    datagen_enable_global_users: bool
    datagen_lookback_days: int
    datagen_progress_every_tenants: int
    datagen_load_method: str
    datagen_sql_batch_tenants: int
    datagen_copy_generator_path: str
    datagen_distribution: str
    datagen_hot_tenant_pct: float
    datagen_hot_event_pct: float
    datagen_base_time_unix: int
    datagen_shard_count: int

    @classmethod
    def from_env(cls) -> DatagenSettings:
        return cls(
            postgres_host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
            postgres_port=int(os.getenv("POSTGRES_PORT", "6432")),
            postgres_user=os.getenv("POSTGRES_USER", "postgres"),
            postgres_password=os.getenv("POSTGRES_PASSWORD", ""),
            postgres_db=os.getenv("POSTGRES_DB", "app"),
            postgres_ssl_mode=os.getenv("POSTGRES_SSL_MODE", "disable"),
            postgres_ssl_root_cert=_resolve_path(os.getenv("POSTGRES_SSL_ROOT_CERT", "")),
            datagen_region=os.getenv("DATAGEN_REGION", "eu"),
            datagen_tenant_start=int(os.getenv("DATAGEN_TENANT_START", "1")),
            datagen_tenant_end=int(os.getenv("DATAGEN_TENANT_END", "1000")),
            datagen_tenant_ranges=os.getenv("DATAGEN_TENANT_RANGES", ""),
            datagen_event_id_mode=os.getenv(
                "DATAGEN_EVENT_ID_MODE", "local_sequential"
            ),
            datagen_output_dir=_resolve_path(os.getenv("DATAGEN_OUTPUT_DIR", "generated/eu")),
            datagen_random_seed=int(os.getenv("DATAGEN_RANDOM_SEED", "42")),
            datagen_events_per_tenant=int(os.getenv("DATAGEN_EVENTS_PER_TENANT", "100")),
            datagen_users_per_tenant=int(os.getenv("DATAGEN_USERS_PER_TENANT", "50")),
            datagen_global_users_per_tenant=int(
                os.getenv(
                    "DATAGEN_GLOBAL_USERS_PER_TENANT",
                    os.getenv("DATAGEN_USERS_PER_TENANT", "50"),
                )
            ),
            datagen_enable_global_users=_parse_bool(
                os.getenv("DATAGEN_ENABLE_GLOBAL_USERS", "false")
            ),
            datagen_lookback_days=int(os.getenv("DATAGEN_LOOKBACK_DAYS", "30")),
            datagen_progress_every_tenants=int(os.getenv("DATAGEN_PROGRESS_EVERY_TENANTS", "1000")),
            datagen_load_method=os.getenv("DATAGEN_LOAD_METHOD", "csv"),
            datagen_sql_batch_tenants=int(os.getenv("DATAGEN_SQL_BATCH_TENANTS", "1000")),
            datagen_copy_generator_path=_resolve_path(
                os.getenv("DATAGEN_COPY_GENERATOR_PATH", "tools/cpp/citus_datagen")
            ),
            datagen_distribution=os.getenv("DATAGEN_DISTRIBUTION", "uniform"),
            datagen_hot_tenant_pct=float(os.getenv("DATAGEN_HOT_TENANT_PCT", "1")),
            datagen_hot_event_pct=float(os.getenv("DATAGEN_HOT_EVENT_PCT", "50")),
            datagen_base_time_unix=int(os.getenv("DATAGEN_BASE_TIME_UNIX", "0")),
            datagen_shard_count=int(os.getenv("DATAGEN_SHARD_COUNT", "32")),
        )

    @property
    def output_dir(self) -> Path:
        return Path(self.datagen_output_dir)

    @property
    def tenants_csv_path(self) -> Path:
        return self.output_dir / "tenants.csv"

    @property
    def events_csv_path(self) -> Path:
        return self.output_dir / "events.csv"

    @property
    def users_csv_path(self) -> Path:
        return self.output_dir / "users.csv"

    @property
    def global_users_csv_path(self) -> Path:
        return self.output_dir / "global_users.csv"

    @property
    def schema_path(self) -> Path:
        return ROOT_DIR / "sql" / "minimal_schema.sql"

    @property
    def copy_generator_path(self) -> Path:
        return Path(self.datagen_copy_generator_path)

    @property
    def tenant_ranges(self) -> tuple[tuple[int, int, str], ...]:
        if not self.datagen_tenant_ranges.strip():
            return (
                (
                    self.datagen_tenant_start,
                    self.datagen_tenant_end,
                    self.datagen_region,
                ),
            )

        ranges: list[tuple[int, int, str]] = []
        for raw_range in self.datagen_tenant_ranges.split(","):
            parts = raw_range.strip().split(":", 2)
            if len(parts) != 3:
                raise ValueError(
                    "DATAGEN_TENANT_RANGES entries must be start:end:logical_region"
                )
            start, end = int(parts[0]), int(parts[1])
            if start > end or not parts[2]:
                raise ValueError(f"Invalid tenant range: {raw_range}")
            ranges.append((start, end, parts[2]))
        return tuple(ranges)

    @property
    def tenant_count(self) -> int:
        return sum(end - start + 1 for start, end, _region in self.tenant_ranges)
