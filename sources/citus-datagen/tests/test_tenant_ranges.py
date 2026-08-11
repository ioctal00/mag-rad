from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda *_args, **_kwargs: None))
DatagenSettings = importlib.import_module("datagen.settings").DatagenSettings


class TenantRangeSettingsTest(unittest.TestCase):
    def test_disjoint_ranges_preserve_logical_region_labels(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATAGEN_TENANT_RANGES": "10001:10100:us,20001:20100:apac",
                "DATAGEN_EVENT_ID_MODE": "tenant_global",
            },
            clear=False,
        ):
            settings = DatagenSettings.from_env()

        self.assertEqual(
            settings.tenant_ranges,
            ((10001, 10100, "us"), (20001, 20100, "apac")),
        )
        self.assertEqual(settings.tenant_count, 200)
        self.assertEqual(settings.datagen_event_id_mode, "tenant_global")

    def test_legacy_single_range_remains_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATAGEN_REGION": "eu",
                "DATAGEN_TENANT_START": "1",
                "DATAGEN_TENANT_END": "10",
                "DATAGEN_TENANT_RANGES": "",
            },
            clear=False,
        ):
            settings = DatagenSettings.from_env()

        self.assertEqual(settings.tenant_ranges, ((1, 10, "eu"),))
        self.assertEqual(settings.tenant_count, 10)


if __name__ == "__main__":
    unittest.main()
