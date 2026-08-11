from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

from .settings import Settings


@dataclass(frozen=True, slots=True)
class PsqlResult:
    elapsed_seconds: float
    started_at_unix: float
    finished_at_unix: float
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class ResultSignature:
    row_count: int
    output_byte_count: int
    multiset_sha256: str
    ordered_sha256: str
    elapsed_seconds: float
    started_at_unix: float
    finished_at_unix: float
    stderr: str


@dataclass(frozen=True, slots=True)
class ResultSnapshot:
    row_count: int
    output_byte_count: int
    multiset_sha256: str
    ordered_sha256: str
    elapsed_seconds: float
    started_at_unix: float
    finished_at_unix: float
    stderr: str
    columns: tuple[tuple[str, str], ...]
    rows_file: Path


RESULT_SNAPSHOT_NULL = "__MASTER_REGIMES_SQL_NULL__"


def _psql_env(settings: Settings) -> dict[str, str]:
    env = dict(os.environ)
    env["PGAPPNAME"] = settings.bench_application_name
    env["PGPASSWORD"] = settings.pg_password
    env["PGSSLMODE"] = settings.pg_sslmode
    if settings.pg_sslrootcert:
        env["PGSSLROOTCERT"] = settings.pg_sslrootcert
    return env


def run_psql(
    settings: Settings,
    *,
    sql_file: Path | None = None,
    sql: str | None = None,
    output_file: Path | None = None,
    csv_output: bool = False,
    variables: dict[str, str | int | float] | None = None,
    extra_env: dict[str, str] | None = None,
    no_psqlrc: bool = False,
    quiet: bool = False,
    tuples_only: bool = False,
    unaligned: bool = False,
) -> PsqlResult:
    if sql_file is None and sql is None:
        raise ValueError("Either sql_file or sql must be provided.")
    if sql_file is not None and sql is not None:
        raise ValueError("Provide only one of sql_file or sql.")

    command = ["psql"]
    if no_psqlrc:
        command.append("-X")
    if quiet:
        command.append("-q")
    if tuples_only:
        command.append("-t")
    if unaligned:
        command.append("-A")
    command.extend(
        [
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            settings.pg_host,
            "-p",
            str(settings.pg_port),
            "-U",
            settings.pg_user,
            "-d",
            settings.pg_database,
        ]
    )

    if csv_output:
        command.append("--csv")
    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        command.extend(["-o", str(output_file)])
    for key, value in (variables or {}).items():
        command.extend(["-v", f"{key}={value}"])
    if sql_file is not None:
        command.extend(["-f", str(sql_file)])

    started_at_unix = time.time()
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        input=sql,
        text=True,
        env={**_psql_env(settings), **(extra_env or {})},
    )
    finished_at_unix = time.time()
    return PsqlResult(
        elapsed_seconds=time.perf_counter() - started,
        started_at_unix=started_at_unix,
        finished_at_unix=finished_at_unix,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def result_signature(
    settings: Settings,
    *,
    sql_file: Path,
    variables: dict[str, str | int | float] | None = None,
    extra_env: dict[str, str] | None = None,
) -> ResultSignature:
    """Execute a query and hash its CSV rows without persisting result rows."""
    command = [
        "psql",
        "-X",
        "-q",
        "-t",
        "--csv",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        settings.pg_host,
        "-p",
        str(settings.pg_port),
        "-U",
        settings.pg_user,
        "-d",
        settings.pg_database,
    ]
    for key, value in (variables or {}).items():
        command.extend(["-v", f"{key}={value}"])
    command.extend(["-f", str(sql_file)])

    started_at_unix = time.time()
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**_psql_env(settings), **(extra_env or {})},
    )
    assert process.stdout is not None
    ordered = hashlib.sha256()
    xor_accumulator = 0
    sum_accumulator = 0
    modulus = 1 << 256
    row_count = 0
    output_byte_count = 0
    for raw_line in process.stdout:
        ordered.update(raw_line)
        output_byte_count += len(raw_line)
        row_digest = hashlib.sha256(raw_line).digest()
        row_value = int.from_bytes(row_digest, byteorder="big")
        xor_accumulator ^= row_value
        sum_accumulator = (sum_accumulator + row_value) % modulus
        row_count += 1
    process.stdout.close()
    stderr_bytes = process.stderr.read() if process.stderr is not None else b""
    if process.stderr is not None:
        process.stderr.close()
    returncode = process.wait()
    finished_at_unix = time.time()
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if returncode != 0:
        raise subprocess.CalledProcessError(
            returncode,
            command,
            output="",
            stderr=stderr,
        )

    multiset_payload: dict[str, Any] = {
        "algorithm": "sha256-row-multiset-v1",
        "row_count": row_count,
        "row_hash_xor": f"{xor_accumulator:064x}",
        "row_hash_sum_mod_2_256": f"{sum_accumulator:064x}",
    }
    return ResultSignature(
        row_count=row_count,
        output_byte_count=output_byte_count,
        multiset_sha256=hashlib.sha256(
            json.dumps(
                multiset_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        ordered_sha256=ordered.hexdigest(),
        elapsed_seconds=time.perf_counter() - started,
        started_at_unix=started_at_unix,
        finished_at_unix=finished_at_unix,
        stderr=stderr,
    )


def _result_psql_command(
    settings: Settings,
    *,
    variables: dict[str, str | int | float] | None = None,
) -> list[str]:
    command = [
        "psql",
        "-X",
        "-q",
        "-t",
        "--csv",
        "-P",
        f"null={RESULT_SNAPSHOT_NULL}",
        "-v",
        "ON_ERROR_STOP=1",
        "-h",
        settings.pg_host,
        "-p",
        str(settings.pg_port),
        "-U",
        settings.pg_user,
        "-d",
        settings.pg_database,
    ]
    for key, value in (variables or {}).items():
        command.extend(["-v", f"{key}={value}"])
    return command


def _query_description_sql(sql_file: Path) -> str:
    query = sql_file.read_text(encoding="utf-8").rstrip()
    if query.endswith(";"):
        query = query[:-1].rstrip()
    if not query:
        raise ValueError(f"SQL file is empty: {sql_file}")
    return f"{query}\n\\gdesc\n"


def result_snapshot(
    settings: Settings,
    *,
    sql_file: Path,
    output_dir: Path,
    variables: dict[str, str | int | float] | None = None,
    extra_env: dict[str, str] | None = None,
) -> ResultSnapshot:
    """Persist a typed query result for a bounded correctness recovery run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    env = {**_psql_env(settings), **(extra_env or {})}
    base_command = _result_psql_command(settings, variables=variables)
    description = subprocess.run(
        base_command,
        check=True,
        capture_output=True,
        input=_query_description_sql(sql_file),
        text=True,
        env=env,
    )
    columns = tuple(
        (row[0], row[1])
        for row in csv.reader(io.StringIO(description.stdout))
        if len(row) >= 2
    )
    if not columns:
        raise RuntimeError(f"Unable to describe query result: {sql_file}")

    rows_file = output_dir / "result_rows.csv"
    command = [*base_command, "-f", str(sql_file)]
    started_at_unix = time.time()
    started = time.perf_counter()
    output_byte_count = 0
    with rows_file.open("wb") as rows_handle:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert process.stdout is not None
        for raw_line in process.stdout:
            rows_handle.write(raw_line)
            output_byte_count += len(raw_line)
        process.stdout.close()
        stderr_bytes = process.stderr.read() if process.stderr is not None else b""
        if process.stderr is not None:
            process.stderr.close()
        returncode = process.wait()
    finished_at_unix = time.time()
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if returncode != 0:
        rows_file.unlink(missing_ok=True)
        raise subprocess.CalledProcessError(
            returncode,
            command,
            output="",
            stderr=stderr,
        )

    raw_output = rows_file.read_bytes()
    ordered = hashlib.sha256(raw_output)
    parsed_rows = list(csv.reader(io.StringIO(raw_output.decode("utf-8"))))
    xor_accumulator = 0
    sum_accumulator = 0
    modulus = 1 << 256
    for row in parsed_rows:
        canonical_row = json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        row_value = int.from_bytes(
            hashlib.sha256(canonical_row).digest(),
            byteorder="big",
        )
        xor_accumulator ^= row_value
        sum_accumulator = (sum_accumulator + row_value) % modulus
    row_count = len(parsed_rows)
    multiset_payload: dict[str, Any] = {
        "algorithm": "sha256-row-multiset-v1",
        "row_count": row_count,
        "row_hash_xor": f"{xor_accumulator:064x}",
        "row_hash_sum_mod_2_256": f"{sum_accumulator:064x}",
    }
    return ResultSnapshot(
        row_count=row_count,
        output_byte_count=output_byte_count,
        multiset_sha256=hashlib.sha256(
            json.dumps(
                multiset_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        ordered_sha256=ordered.hexdigest(),
        elapsed_seconds=time.perf_counter() - started,
        started_at_unix=started_at_unix,
        finished_at_unix=finished_at_unix,
        stderr=stderr,
        columns=columns,
        rows_file=rows_file,
    )
