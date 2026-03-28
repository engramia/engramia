# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Čermák
"""Code snippet catalog for recall quality tests.

Each cluster has three quality tiers: good (8.5-9.5), medium (5.5-6.5), bad (2.0-3.5).
Snippets are deterministic Python strings — no LLM calls required.
"""
from .c01_csv_filter import BAD as C01_BAD
from .c01_csv_filter import GOOD as C01_GOOD
from .c01_csv_filter import MEDIUM as C01_MEDIUM
from .c02_csv_aggregate import BAD as C02_BAD
from .c02_csv_aggregate import GOOD as C02_GOOD
from .c02_csv_aggregate import MEDIUM as C02_MEDIUM
from .c03_toml_validation import BAD as C03_BAD
from .c03_toml_validation import GOOD as C03_GOOD
from .c03_toml_validation import MEDIUM as C03_MEDIUM
from .c04_yaml_merge import BAD as C04_BAD
from .c04_yaml_merge import GOOD as C04_GOOD
from .c04_yaml_merge import MEDIUM as C04_MEDIUM
from .c05_http_retry import BAD as C05_BAD
from .c05_http_retry import GOOD as C05_GOOD
from .c05_http_retry import MEDIUM as C05_MEDIUM
from .c06_pagination import BAD as C06_BAD
from .c06_pagination import GOOD as C06_GOOD
from .c06_pagination import MEDIUM as C06_MEDIUM
from .c07_moving_average import BAD as C07_BAD
from .c07_moving_average import GOOD as C07_GOOD
from .c07_moving_average import MEDIUM as C07_MEDIUM
from .c08_zscore import BAD as C08_BAD
from .c08_zscore import GOOD as C08_GOOD
from .c08_zscore import MEDIUM as C08_MEDIUM
from .c09_async_batch import BAD as C09_BAD
from .c09_async_batch import GOOD as C09_GOOD
from .c09_async_batch import MEDIUM as C09_MEDIUM
from .c10_email_regex import BAD as C10_BAD
from .c10_email_regex import GOOD as C10_GOOD
from .c10_email_regex import MEDIUM as C10_MEDIUM
from .c11_pg_upsert import BAD as C11_BAD
from .c11_pg_upsert import GOOD as C11_GOOD
from .c11_pg_upsert import MEDIUM as C11_MEDIUM
from .c12_file_dedup import BAD as C12_BAD
from .c12_file_dedup import GOOD as C12_GOOD
from .c12_file_dedup import MEDIUM as C12_MEDIUM

CLUSTER_SNIPPETS: dict[str, dict[str, dict]] = {
    "C01": {"good": C01_GOOD, "medium": C01_MEDIUM, "bad": C01_BAD},
    "C02": {"good": C02_GOOD, "medium": C02_MEDIUM, "bad": C02_BAD},
    "C03": {"good": C03_GOOD, "medium": C03_MEDIUM, "bad": C03_BAD},
    "C04": {"good": C04_GOOD, "medium": C04_MEDIUM, "bad": C04_BAD},
    "C05": {"good": C05_GOOD, "medium": C05_MEDIUM, "bad": C05_BAD},
    "C06": {"good": C06_GOOD, "medium": C06_MEDIUM, "bad": C06_BAD},
    "C07": {"good": C07_GOOD, "medium": C07_MEDIUM, "bad": C07_BAD},
    "C08": {"good": C08_GOOD, "medium": C08_MEDIUM, "bad": C08_BAD},
    "C09": {"good": C09_GOOD, "medium": C09_MEDIUM, "bad": C09_BAD},
    "C10": {"good": C10_GOOD, "medium": C10_MEDIUM, "bad": C10_BAD},
    "C11": {"good": C11_GOOD, "medium": C11_MEDIUM, "bad": C11_BAD},
    "C12": {"good": C12_GOOD, "medium": C12_MEDIUM, "bad": C12_BAD},
}

__all__ = ["CLUSTER_SNIPPETS"]
