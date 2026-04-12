# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Marek Cermak
"""A05 — Data Pipeline / ETL snippets (good / medium / bad).

Domain: Building ETL pipelines — ingestion, transformation, loading, error handling.
"""

GOOD: dict = {
    "eval_score": 9.3,
    "output": "ETL pipeline processed 12,847 events from S3. 12,801 loaded to Postgres, 46 quarantined (schema violations).",
    "code": '''\
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Iterator

import boto3
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    ingested: int = 0
    transformed: int = 0
    loaded: int = 0
    quarantined: int = 0
    errors: list[str] = field(default_factory=list)


class EventETLPipeline:
    """ETL pipeline: S3 JSON events → normalize → Postgres.

    Stages:
        1. Ingest: stream JSON lines from S3 objects
        2. Transform: normalize timestamps, validate schema, enrich
        3. Load: batch INSERT into Postgres events table
        4. Quarantine: malformed records → separate table for review
    """

    BATCH_SIZE = 500

    def __init__(self, s3_client, db_session: AsyncSession, bucket: str) -> None:
        self._s3 = s3_client
        self._db = db_session
        self._bucket = bucket

    def ingest(self, prefix: str) -> Iterator[dict[str, Any]]:
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                response = self._s3.get_object(Bucket=self._bucket, Key=obj["Key"])
                for line in response["Body"].iter_lines():
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning("Skipping malformed line in %s: %s", obj["Key"], exc)

    def transform(self, record: dict[str, Any]) -> dict[str, Any] | None:
        required = {"event_type", "timestamp", "payload"}
        if not required.issubset(record.keys()):
            return None
        ts_raw = record["timestamp"]
        if isinstance(ts_raw, (int, float)):
            ts = datetime.fromtimestamp(ts_raw, tz=UTC)
        else:
            ts = datetime.fromisoformat(ts_raw).replace(tzinfo=UTC)
        return {
            "event_type": record["event_type"],
            "occurred_at": ts,
            "payload": json.dumps(record["payload"]),
            "source": record.get("source", "unknown"),
            "ingested_at": datetime.now(UTC),
        }

    async def load_batch(self, batch: list[dict]) -> int:
        if not batch:
            return 0
        stmt = insert(events_table).values(batch)
        await self._db.execute(stmt)
        await self._db.commit()
        return len(batch)

    async def run(self, prefix: str) -> PipelineStats:
        stats = PipelineStats()
        batch: list[dict] = []

        for raw in self.ingest(prefix):
            stats.ingested += 1
            transformed = self.transform(raw)
            if transformed is None:
                stats.quarantined += 1
                continue
            stats.transformed += 1
            batch.append(transformed)

            if len(batch) >= self.BATCH_SIZE:
                loaded = await self.load_batch(batch)
                stats.loaded += loaded
                batch.clear()

        if batch:
            stats.loaded += await self.load_batch(batch)

        logger.info(
            "Pipeline complete: ingested=%d transformed=%d loaded=%d quarantined=%d",
            stats.ingested, stats.transformed, stats.loaded, stats.quarantined,
        )
        return stats
''',
}

MEDIUM: dict = {
    "eval_score": 6.2,
    "output": "ETL pipeline runs, loads events to database.",
    "code": """\
import json
import boto3

def run_etl(bucket, prefix, db_conn):
    s3 = boto3.client("s3")
    objects = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    count = 0
    for obj in objects.get("Contents", []):
        body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
        for line in body.decode().splitlines():
            record = json.loads(line)
            db_conn.execute(
                "INSERT INTO events (event_type, payload, ts) VALUES (%s, %s, %s)",
                (record["event_type"], json.dumps(record["payload"]), record["timestamp"])
            )
            count += 1
    db_conn.commit()
    return count
""",
}

BAD: dict = {
    "eval_score": 2.0,
    "output": "loads some data",
    "code": """\
import json, boto3

def etl(bucket, key):
    data = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    records = json.loads(data)
    # TODO: transform and load
    return records
""",
}
