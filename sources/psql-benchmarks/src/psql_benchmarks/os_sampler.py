from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import statistics
import subprocess
import threading
import time


def _read_first_line(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").splitlines()[0]
    except (FileNotFoundError, IndexError, PermissionError):
        return ""


def _read_proc_stat() -> dict[str, int]:
    parts = _read_first_line(Path("/proc/stat")).split()
    if not parts or parts[0] != "cpu":
        return {}
    keys = [
        "user",
        "nice",
        "system",
        "idle",
        "iowait",
        "irq",
        "softirq",
        "steal",
        "guest",
        "guest_nice",
    ]
    return {key: int(value) for key, value in zip(keys, parts[1:], strict=False)}


def _read_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw_value = line.split(":", 1)
            values[key] = int(raw_value.strip().split()[0])
    except (FileNotFoundError, PermissionError, ValueError):
        return {}
    return values


def _read_net_stats() -> dict[str, dict[str, int]]:
    root = Path("/sys/class/net")
    stats: dict[str, dict[str, int]] = {}
    for iface in root.iterdir() if root.exists() else []:
        if iface.name == "lo":
            continue
        stats_dir = iface / "statistics"
        try:
            stats[iface.name] = {
                "rx_bytes": int((stats_dir / "rx_bytes").read_text(encoding="utf-8")),
                "tx_bytes": int((stats_dir / "tx_bytes").read_text(encoding="utf-8")),
                "rx_packets": int((stats_dir / "rx_packets").read_text(encoding="utf-8")),
                "tx_packets": int((stats_dir / "tx_packets").read_text(encoding="utf-8")),
                "rx_dropped": int((stats_dir / "rx_dropped").read_text(encoding="utf-8")),
                "tx_dropped": int((stats_dir / "tx_dropped").read_text(encoding="utf-8")),
                "rx_errors": int((stats_dir / "rx_errors").read_text(encoding="utf-8")),
                "tx_errors": int((stats_dir / "tx_errors").read_text(encoding="utf-8")),
            }
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    return stats


def _read_proc_protocol_stats(path: Path) -> dict[str, dict[str, int]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError):
        return {}

    result: dict[str, dict[str, int]] = {}
    for index in range(0, len(lines) - 1, 2):
        header = lines[index].split()
        values = lines[index + 1].split()
        if not header or not values or header[0] != values[0]:
            continue
        protocol = header[0].rstrip(":")
        try:
            result[protocol] = {
                key: int(value) for key, value in zip(header[1:], values[1:], strict=False)
            }
        except ValueError:
            continue
    return result


def _read_tcp_stats() -> dict[str, int]:
    snmp = _read_proc_protocol_stats(Path("/proc/net/snmp")).get("Tcp", {})
    netstat = _read_proc_protocol_stats(Path("/proc/net/netstat")).get("TcpExt", {})
    return {
        "in_segs": int(snmp.get("InSegs", 0)),
        "out_segs": int(snmp.get("OutSegs", 0)),
        "retrans_segs": int(snmp.get("RetransSegs", 0)),
        "active_opens": int(snmp.get("ActiveOpens", 0)),
        "passive_opens": int(snmp.get("PassiveOpens", 0)),
        "estab_resets": int(snmp.get("EstabResets", 0)),
        "out_rsts": int(snmp.get("OutRsts", 0)),
        "lost_retransmit": int(netstat.get("TCPLostRetransmit", 0)),
        "fast_retrans": int(netstat.get("TCPFastRetrans", 0)),
        "timeouts": int(netstat.get("TCPTimeouts", 0)),
    }


def _read_qdisc() -> list[dict] | str:
    try:
        completed = subprocess.run(
            ["tc", "-s", "-j", "qdisc", "show"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        value = json.loads(completed.stdout or "[]")
        return value if isinstance(value, list) else []
    except (
        FileNotFoundError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ):
        try:
            completed = subprocess.run(
                ["tc", "-s", "qdisc", "show"],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            return completed.stdout.strip()
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            return ""


def _read_diskstats() -> dict[str, dict[str, int]]:
    stats: dict[str, dict[str, int]] = {}
    try:
        lines = Path("/proc/diskstats").read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError):
        return stats

    for line in lines:
        parts = line.split()
        if len(parts) < 14:
            continue
        name = parts[2]
        if name.startswith(("loop", "ram")):
            continue
        stats[name] = {
            "reads_completed": int(parts[3]),
            "sectors_read": int(parts[5]),
            "time_reading_ms": int(parts[6]),
            "writes_completed": int(parts[7]),
            "sectors_written": int(parts[9]),
            "time_writing_ms": int(parts[10]),
            "io_in_progress": int(parts[11]),
            "time_doing_io_ms": int(parts[12]),
        }
    return stats


def collect_sample(*, include_qdisc: bool = True) -> dict:
    return {
        "ts_unix": time.time(),
        "cpu": _read_proc_stat(),
        "meminfo_kb": _read_meminfo(),
        "net": _read_net_stats(),
        "tcp": _read_tcp_stats(),
        "qdisc": _read_qdisc() if include_qdisc else None,
        "disk": _read_diskstats(),
    }


def _cpu_busy_ratio(first: dict[str, int], last: dict[str, int]) -> float | None:
    keys = set(first) & set(last)
    if not keys:
        return None

    deltas = {key: max(0, last[key] - first[key]) for key in keys}
    total = sum(deltas.values())
    if total == 0:
        return None

    idle = deltas.get("idle", 0) + deltas.get("iowait", 0)
    return (total - idle) / total


def _cpu_counter_ratio(
    first: dict[str, int],
    last: dict[str, int],
    counter: str,
) -> float | None:
    keys = set(first) & set(last)
    if not keys or counter not in keys:
        return None

    deltas = {key: max(0, last[key] - first[key]) for key in keys}
    total = sum(deltas.values())
    if total == 0:
        return None
    return deltas[counter] / total


def _mem_used_bytes(sample: dict) -> int | None:
    meminfo = sample.get("meminfo_kb", {})
    if not isinstance(meminfo, dict):
        return None
    total_kb = meminfo.get("MemTotal")
    available_kb = meminfo.get("MemAvailable")
    if total_kb is None or available_kb is None:
        return None
    return max(0, int(total_kb) - int(available_kb)) * 1024


def _summarize_sample_rows(samples: list[dict]) -> dict:
    if len(samples) < 2:
        return {"sample_count": len(samples)}

    first = samples[0]
    last = samples[-1]
    duration_seconds = max(0.0, float(last["ts_unix"]) - float(first["ts_unix"]))

    net_delta: dict[str, dict[str, int]] = {}
    for iface, first_stats in first.get("net", {}).items():
        last_stats = last.get("net", {}).get(iface, {})
        net_delta[iface] = {
            key: max(0, int(last_stats.get(key, 0)) - int(first_stats.get(key, 0)))
            for key in (
                "rx_bytes",
                "tx_bytes",
                "rx_packets",
                "tx_packets",
                "rx_dropped",
                "tx_dropped",
                "rx_errors",
                "tx_errors",
            )
        }

    tcp_delta = {
        key: max(
            0,
            int(last.get("tcp", {}).get(key, 0)) - int(first.get("tcp", {}).get(key, 0)),
        )
        for key in set(first.get("tcp", {})) | set(last.get("tcp", {}))
    }

    disk_delta: dict[str, dict[str, int | float]] = {}
    for disk, first_stats in first.get("disk", {}).items():
        last_stats = last.get("disk", {}).get(disk, {})
        sectors_read = max(
            0, int(last_stats.get("sectors_read", 0)) - int(first_stats.get("sectors_read", 0))
        )
        sectors_written = max(
            0,
            int(last_stats.get("sectors_written", 0)) - int(first_stats.get("sectors_written", 0)),
        )
        disk_delta[disk] = {
            "read_bytes": sectors_read * 512,
            "written_bytes": sectors_written * 512,
            "reads_completed": max(
                0,
                int(last_stats.get("reads_completed", 0))
                - int(first_stats.get("reads_completed", 0)),
            ),
            "writes_completed": max(
                0,
                int(last_stats.get("writes_completed", 0))
                - int(first_stats.get("writes_completed", 0)),
            ),
        }

    first_cpu = first.get("cpu", {})
    last_cpu = last.get("cpu", {})
    busy_ratio = _cpu_busy_ratio(first_cpu, last_cpu)
    steal_ratio = _cpu_counter_ratio(first_cpu, last_cpu, "steal")
    mem_used_values = [
        value for sample in samples if (value := _mem_used_bytes(sample)) is not None
    ]
    mem_available_values = [
        int(meminfo.get("MemAvailable", 0)) * 1024
        for sample in samples
        if isinstance((meminfo := sample.get("meminfo_kb")), dict) and "MemAvailable" in meminfo
    ]
    first_meminfo = first.get("meminfo_kb", {}) if isinstance(first.get("meminfo_kb"), dict) else {}
    last_meminfo = last.get("meminfo_kb", {}) if isinstance(last.get("meminfo_kb"), dict) else {}
    return {
        "sample_count": len(samples),
        "duration_seconds": duration_seconds,
        "cpu_busy_pct": None if busy_ratio is None else round(busy_ratio * 100, 3),
        "cpu_steal_pct": None if steal_ratio is None else round(steal_ratio * 100, 3),
        "mem": {
            "total_bytes": int(first_meminfo.get("MemTotal", 0)) * 1024,
            "first_used_bytes": _mem_used_bytes(first) or 0,
            "last_used_bytes": _mem_used_bytes(last) or 0,
            "min_used_bytes": min(mem_used_values, default=0),
            "max_used_bytes": max(mem_used_values, default=0),
            "min_available_bytes": min(
                mem_available_values,
                default=0,
            ),
            "max_available_bytes": max(
                mem_available_values,
                default=0,
            ),
            "first_available_bytes": int(first_meminfo.get("MemAvailable", 0)) * 1024,
            "last_available_bytes": int(last_meminfo.get("MemAvailable", 0)) * 1024,
            "first_swap_free_bytes": int(first_meminfo.get("SwapFree", 0)) * 1024,
            "last_swap_free_bytes": int(last_meminfo.get("SwapFree", 0)) * 1024,
            "swap_total_bytes": int(first_meminfo.get("SwapTotal", 0)) * 1024,
        },
        "telemetry_window": {
            "started_at_unix": float(first["ts_unix"]),
            "finished_at_unix": float(last["ts_unix"]),
        },
        "first_sample": first,
        "last_sample": last,
        "net_delta": net_delta,
        "tcp_delta": tcp_delta,
        "qdisc_before": first.get("qdisc", []),
        "qdisc_after": last.get("qdisc", []),
        "disk_delta": disk_delta,
    }


def summarize_samples(
    path: Path,
    *,
    window_started_at_unix: float | None = None,
    window_finished_at_unix: float | None = None,
) -> dict:
    samples = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                samples.append(json.loads(line))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"sample_count": 0}

    samples.sort(key=lambda sample: float(sample.get("ts_unix", 0.0)))
    if window_started_at_unix is None or window_finished_at_unix is None:
        summary = _summarize_sample_rows(samples)
        summary["summary_scope"] = "capture_envelope"
        summary["raw_sample_count"] = len(samples)
        return summary
    if window_finished_at_unix < window_started_at_unix:
        raise ValueError("Query telemetry window finishes before it starts.")
    if len(samples) < 2:
        return {
            "sample_count": len(samples),
            "raw_sample_count": len(samples),
            "summary_scope": "query_bracket",
            "alignment": {
                "status": "insufficient_samples",
                "query_started_at_unix": window_started_at_unix,
                "query_finished_at_unix": window_finished_at_unix,
            },
        }

    start_index = max(
        (
            index
            for index, sample in enumerate(samples)
            if float(sample["ts_unix"]) <= window_started_at_unix
        ),
        default=0,
    )
    end_index = next(
        (
            index
            for index, sample in enumerate(samples)
            if float(sample["ts_unix"]) >= window_finished_at_unix
        ),
        len(samples) - 1,
    )
    if end_index <= start_index:
        end_index = min(len(samples) - 1, start_index + 1)
    selected = samples[start_index : end_index + 1]
    summary = _summarize_sample_rows(selected)
    # Reading qdisc state invokes `tc` and is intentionally limited to capture
    # boundaries. It is static context for the query bracket, not a 4 Hz metric.
    summary["qdisc_before"] = samples[0].get("qdisc", [])
    summary["qdisc_after"] = samples[-1].get("qdisc", [])
    summary["qdisc_scope"] = "capture_envelope_static_context"
    selected_start = float(selected[0]["ts_unix"])
    selected_finish = float(selected[-1]["ts_unix"])
    intervals = [
        float(current["ts_unix"]) - float(previous["ts_unix"])
        for previous, current in zip(samples, samples[1:], strict=False)
        if float(current["ts_unix"]) >= float(previous["ts_unix"])
    ]
    median_interval = statistics.median(intervals) if intervals else 0.0
    pre_padding = max(0.0, window_started_at_unix - selected_start)
    post_padding = max(0.0, selected_finish - window_finished_at_unix)
    query_duration = window_finished_at_unix - window_started_at_unix
    coverage = (
        selected_start <= window_started_at_unix and selected_finish >= window_finished_at_unix
    )
    interior_count = sum(
        window_started_at_unix <= float(sample["ts_unix"]) <= window_finished_at_unix
        for sample in samples
    )
    padding = pre_padding + post_padding
    if not coverage:
        alignment_status = "incomplete_coverage"
    elif median_interval <= 0.3 and padding <= 0.65:
        alignment_status = "high"
    elif median_interval <= 1.1 and padding <= 2.2:
        alignment_status = "medium"
    else:
        alignment_status = "low"
    summary.update(
        {
            "summary_scope": "query_bracket",
            "raw_sample_count": len(samples),
            "alignment": {
                "status": alignment_status,
                "coverage": coverage,
                "query_started_at_unix": window_started_at_unix,
                "query_finished_at_unix": window_finished_at_unix,
                "query_duration_seconds": query_duration,
                "selected_started_at_unix": selected_start,
                "selected_finished_at_unix": selected_finish,
                "pre_query_padding_seconds": pre_padding,
                "post_query_padding_seconds": post_padding,
                "total_padding_seconds": padding,
                "median_sample_interval_seconds": median_interval,
                "interior_sample_count": interior_count,
            },
        }
    )
    return summary


@dataclass(slots=True)
class OsSampler:
    output_file: Path
    interval_seconds: float
    _stop_event: threading.Event = field(init=False, repr=False)
    _thread: threading.Thread | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self._stop_event = threading.Event()

    def start(self) -> None:
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=max(2.0, self.interval_seconds * 2))

    def _run(self) -> None:
        with self.output_file.open("a", encoding="utf-8") as handle:
            while not self._stop_event.is_set():
                handle.write(json.dumps(collect_sample(), sort_keys=True) + "\n")
                handle.flush()
                self._stop_event.wait(self.interval_seconds)
