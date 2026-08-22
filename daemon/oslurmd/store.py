from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class JobStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                """
                create table if not exists jobs (
                    slurm_job_id text primary key,
                    oslurm_job_id text not null,
                    spec_json text not null,
                    created_at integer not null
                )
                """
            )

    def bind(self, slurm_job_id: str, oslurm_job_id: str, spec: dict) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "insert or replace into jobs values (?, ?, ?, ?)",
                (slurm_job_id, oslurm_job_id, json.dumps(spec), int(time.time())),
            )

