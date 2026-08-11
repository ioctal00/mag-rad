from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from src.psql_benchmarks.os_sampler import summarize_samples
from src.psql_benchmarks.psql import (
    RESULT_SNAPSHOT_NULL,
    result_signature,
    result_snapshot,
)
from src.psql_benchmarks.settings import _load_env_files


class RawCollectionTests(unittest.TestCase):
    def test_explicit_process_environment_overrides_env_files(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"BENCH_SAMPLE_INTERVAL_SECONDS": "0.25"},
        ):
            _load_env_files()
            self.assertEqual(
                os.environ["BENCH_SAMPLE_INTERVAL_SECONDS"],
                "0.25",
            )

    def test_os_summary_keeps_raw_network_tcp_qdisc_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "samples.jsonl"
            first = {
                "ts_unix": 10.0,
                "cpu": {"user": 10, "idle": 90},
                "meminfo_kb": {
                    "MemTotal": 1000,
                    "MemAvailable": 600,
                    "SwapTotal": 100,
                    "SwapFree": 90,
                },
                "net": {
                    "eth0": {
                        "rx_bytes": 100,
                        "tx_bytes": 200,
                        "rx_packets": 10,
                        "tx_packets": 20,
                        "rx_dropped": 1,
                        "tx_dropped": 2,
                        "rx_errors": 3,
                        "tx_errors": 4,
                    }
                },
                "tcp": {"retrans_segs": 5, "timeouts": 1},
                "qdisc": [{"kind": "netem"}],
                "disk": {},
            }
            last = {
                **first,
                "ts_unix": 12.0,
                "cpu": {"user": 30, "idle": 170},
                "meminfo_kb": {
                    "MemTotal": 1000,
                    "MemAvailable": 500,
                    "SwapTotal": 100,
                    "SwapFree": 80,
                },
                "net": {
                    "eth0": {
                        "rx_bytes": 500,
                        "tx_bytes": 900,
                        "rx_packets": 30,
                        "tx_packets": 50,
                        "rx_dropped": 2,
                        "tx_dropped": 5,
                        "rx_errors": 3,
                        "tx_errors": 6,
                    }
                },
                "tcp": {"retrans_segs": 9, "timeouts": 3},
                "qdisc": [{"kind": "fq_codel"}],
            }
            path.write_text(
                json.dumps(first) + "\n" + json.dumps(last) + "\n",
                encoding="utf-8",
            )
            summary = summarize_samples(path)
            self.assertEqual(summary["net_delta"]["eth0"]["tx_bytes"], 700)
            self.assertEqual(summary["net_delta"]["eth0"]["tx_dropped"], 3)
            self.assertEqual(summary["tcp_delta"]["retrans_segs"], 4)
            self.assertEqual(summary["mem"]["first_swap_free_bytes"], 90 * 1024)
            self.assertEqual(summary["qdisc_before"][0]["kind"], "netem")
            self.assertEqual(summary["qdisc_after"][0]["kind"], "fq_codel")

    def test_os_summary_brackets_only_the_requested_query_window(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            path = Path(raw_dir) / "samples.jsonl"
            samples = []
            for index, timestamp in enumerate((9.75, 10.0, 10.25, 10.5, 10.75)):
                samples.append(
                    {
                        "ts_unix": timestamp,
                        "cpu": {"user": index * 10, "idle": index * 90},
                        "meminfo_kb": {
                            "MemTotal": 1000,
                            "MemAvailable": 600 - index,
                        },
                        "net": {
                            "eth0": {
                                "rx_bytes": index * 100,
                                "tx_bytes": index * 200,
                            }
                        },
                        "tcp": {},
                        "qdisc": (
                            [{"kind": "netem"}]
                            if index in {0, 4}
                            else []
                        ),
                        "disk": {},
                    }
                )
            path.write_text(
                "".join(json.dumps(sample) + "\n" for sample in samples),
                encoding="utf-8",
            )

            summary = summarize_samples(
                path,
                window_started_at_unix=10.1,
                window_finished_at_unix=10.4,
            )

            self.assertEqual(summary["summary_scope"], "query_bracket")
            self.assertEqual(
                summary["qdisc_scope"],
                "capture_envelope_static_context",
            )
            self.assertEqual(summary["qdisc_before"][0]["kind"], "netem")
            self.assertEqual(summary["sample_count"], 3)
            self.assertEqual(summary["raw_sample_count"], 5)
            self.assertEqual(summary["net_delta"]["eth0"]["tx_bytes"], 400)
            self.assertTrue(summary["alignment"]["coverage"])
            self.assertEqual(summary["alignment"]["status"], "high")
            self.assertAlmostEqual(
                summary["alignment"]["total_padding_seconds"],
                0.2,
            )

    def test_result_signature_streams_rows_without_result_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            fake_psql = root / "psql"
            fake_psql.write_text(
                "#!/bin/sh\nprintf '2,beta\\n1,alpha\\n2,beta\\n'\n",
                encoding="utf-8",
            )
            fake_psql.chmod(0o755)
            sql_file = root / "query.sql"
            sql_file.write_text("select 1;\n", encoding="utf-8")
            settings = type(
                "Settings",
                (),
                {
                    "bench_application_name": "test",
                    "pg_password": "",
                    "pg_sslmode": "disable",
                    "pg_sslrootcert": "",
                    "pg_host": "localhost",
                    "pg_port": 5432,
                    "pg_user": "postgres",
                    "pg_database": "app",
                },
            )()
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{root}:{old_path}"
            try:
                signature = result_signature(settings, sql_file=sql_file)
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(signature.row_count, 3)
            self.assertGreater(signature.output_byte_count, 0)
            self.assertEqual(len(signature.multiset_sha256), 64)
            self.assertEqual(len(signature.ordered_sha256), 64)
            self.assertEqual({path.name for path in root.iterdir()}, {"psql", "query.sql"})

    def test_result_snapshot_persists_typed_rows_for_correctness_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw_dir:
            root = Path(raw_dir)
            fake_psql = root / "psql"
            fake_psql.write_text(
                "#!/bin/sh\n"
                'case " $* " in\n'
                f"  *\" -f \"*) printf '1,10.25\\n2,{RESULT_SNAPSHOT_NULL}\\n' ;;\n"
                "  *) cat >/dev/null; printf 'id,bigint\\nvalue,double precision\\n' ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            fake_psql.chmod(0o755)
            sql_file = root / "query.sql"
            sql_file.write_text("select 1;\n", encoding="utf-8")
            settings = type(
                "Settings",
                (),
                {
                    "bench_application_name": "test",
                    "pg_password": "",
                    "pg_sslmode": "disable",
                    "pg_sslrootcert": "",
                    "pg_host": "localhost",
                    "pg_port": 5432,
                    "pg_user": "postgres",
                    "pg_database": "app",
                },
            )()
            old_path = os.environ.get("PATH", "")
            os.environ["PATH"] = f"{root}:{old_path}"
            try:
                snapshot = result_snapshot(
                    settings,
                    sql_file=sql_file,
                    output_dir=root / "snapshot",
                )
            finally:
                os.environ["PATH"] = old_path
            self.assertEqual(snapshot.row_count, 2)
            self.assertEqual(
                snapshot.columns,
                (("id", "bigint"), ("value", "double precision")),
            )
            self.assertEqual(
                snapshot.rows_file.read_text(encoding="utf-8"),
                f"1,10.25\n2,{RESULT_SNAPSHOT_NULL}\n",
            )


if __name__ == "__main__":
    unittest.main()
