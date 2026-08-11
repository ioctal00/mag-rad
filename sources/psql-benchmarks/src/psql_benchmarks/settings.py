from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _load_env_files() -> None:
    file_values: dict[str, str] = {}
    for path in (ROOT_DIR / ".env.development", ROOT_DIR / ".env"):
        file_values.update(_parse_env_file(path))
    for key, value in file_values.items():
        # Process values are explicit runtime overrides. Among files, `.env`
        # overrides the development defaults because it is merged last.
        os.environ.setdefault(key, value)


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def _resolve_path(value: str) -> str:
    if not value:
        return ""
    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)
    return str((ROOT_DIR / candidate).resolve())


_load_env_files()


@dataclass(frozen=True, slots=True)
class Settings:
    bench_node_role: str
    bench_region: str
    bench_run_dir: str
    bench_sample_interval_seconds: float
    bench_capture_duration_seconds: float
    bench_warmup_iterations: int
    bench_measurement_iterations: int
    bench_application_name: str
    bench_cluster_label: str
    bench_dataset_label: str
    bench_notes: str
    datagen_region: str
    datagen_tenant_start: str
    datagen_tenant_end: str
    datagen_random_seed: str
    datagen_events_per_tenant: str
    datagen_users_per_tenant: str
    datagen_enable_global_users: str
    datagen_lookback_days: str
    datagen_load_method: str
    datagen_distribution: str
    datagen_hot_tenant_pct: str
    datagen_hot_event_pct: str
    datagen_base_time_unix: str
    pg_host: str
    pg_port: int
    pg_database: str
    pg_user: str
    pg_password: str
    pg_sslmode: str
    pg_sslrootcert: str

    @classmethod
    def from_env(cls) -> Settings:
        settings = cls(
            bench_node_role=os.getenv("BENCH_NODE_ROLE", "coordinator"),
            bench_region=os.getenv("BENCH_REGION", "eu"),
            bench_run_dir=_resolve_path(os.getenv("BENCH_RUN_DIR", "runs")),
            bench_sample_interval_seconds=float(os.getenv("BENCH_SAMPLE_INTERVAL_SECONDS", "1")),
            bench_capture_duration_seconds=float(os.getenv("BENCH_CAPTURE_DURATION_SECONDS", "30")),
            bench_warmup_iterations=int(os.getenv("BENCH_WARMUP_ITERATIONS", "1")),
            bench_measurement_iterations=int(os.getenv("BENCH_MEASUREMENT_ITERATIONS", "5")),
            bench_application_name=os.getenv("BENCH_APPLICATION_NAME", "psql-benchmarks"),
            bench_cluster_label=os.getenv("BENCH_CLUSTER_LABEL", "eu-citus-single-region"),
            bench_dataset_label=os.getenv("BENCH_DATASET_LABEL", "citus-datagen-minimal"),
            bench_notes=os.getenv("BENCH_NOTES", ""),
            datagen_region=os.getenv("DATAGEN_REGION", ""),
            datagen_tenant_start=os.getenv("DATAGEN_TENANT_START", ""),
            datagen_tenant_end=os.getenv("DATAGEN_TENANT_END", ""),
            datagen_random_seed=os.getenv("DATAGEN_RANDOM_SEED", ""),
            datagen_events_per_tenant=os.getenv("DATAGEN_EVENTS_PER_TENANT", ""),
            datagen_users_per_tenant=os.getenv("DATAGEN_USERS_PER_TENANT", ""),
            datagen_enable_global_users=os.getenv("DATAGEN_ENABLE_GLOBAL_USERS", ""),
            datagen_lookback_days=os.getenv("DATAGEN_LOOKBACK_DAYS", ""),
            datagen_load_method=os.getenv("DATAGEN_LOAD_METHOD", ""),
            datagen_distribution=os.getenv("DATAGEN_DISTRIBUTION", ""),
            datagen_hot_tenant_pct=os.getenv("DATAGEN_HOT_TENANT_PCT", ""),
            datagen_hot_event_pct=os.getenv("DATAGEN_HOT_EVENT_PCT", ""),
            datagen_base_time_unix=os.getenv("DATAGEN_BASE_TIME_UNIX", ""),
            pg_host=_env_first("PGHOST", "POSTGRES_HOST", default="127.0.0.1"),
            pg_port=int(_env_first("PGPORT", "POSTGRES_PORT", default="5432")),
            pg_database=_env_first("PGDATABASE", "POSTGRES_DB", default="app"),
            pg_user=_env_first("PGUSER", "POSTGRES_USER", default="postgres"),
            pg_password=_env_first("PGPASSWORD", "POSTGRES_PASSWORD", default=""),
            pg_sslmode=_env_first("PGSSLMODE", "POSTGRES_SSL_MODE", default="disable"),
            pg_sslrootcert=_resolve_path(
                _env_first("PGSSLROOTCERT", "POSTGRES_SSL_ROOT_CERT", default="")
            ),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.bench_sample_interval_seconds <= 0:
            raise ValueError("BENCH_SAMPLE_INTERVAL_SECONDS must be greater than 0.")
        if self.bench_capture_duration_seconds <= 0:
            raise ValueError("BENCH_CAPTURE_DURATION_SECONDS must be greater than 0.")
        if self.bench_warmup_iterations < 0:
            raise ValueError("BENCH_WARMUP_ITERATIONS must be 0 or greater.")
        if self.bench_measurement_iterations < 1:
            raise ValueError("BENCH_MEASUREMENT_ITERATIONS must be 1 or greater.")
        if self.pg_sslmode not in {
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        }:
            raise ValueError(f"Unsupported PGSSLMODE: {self.pg_sslmode}")

    @property
    def run_root(self) -> Path:
        return Path(self.bench_run_dir)

    @property
    def datagen_parameters(self) -> dict[str, str]:
        return {
            "region": self.datagen_region,
            "tenant_start": self.datagen_tenant_start,
            "tenant_end": self.datagen_tenant_end,
            "random_seed": self.datagen_random_seed,
            "events_per_tenant": self.datagen_events_per_tenant,
            "users_per_tenant": self.datagen_users_per_tenant,
            "enable_global_users": self.datagen_enable_global_users,
            "lookback_days": self.datagen_lookback_days,
            "load_method": self.datagen_load_method,
            "distribution": self.datagen_distribution,
            "hot_tenant_pct": self.datagen_hot_tenant_pct,
            "hot_event_pct": self.datagen_hot_event_pct,
            "base_time_unix": self.datagen_base_time_unix,
        }
