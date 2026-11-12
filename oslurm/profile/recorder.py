from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .schema import TRACE_SCHEMA_VERSION, TraceEvent, TraceEventType, TraceHeader, category_for
from .sinks import InMemoryTraceSink, JsonlTraceSink, TraceSink


@dataclass(frozen=True)
class ProfilingConfig:
    mode: str = "light"
    trace: bool = False
    snapshot_interval_sim_s: int = 60
    node_snapshot_interval_sim_s: int = 30
    job_progress_interval_sim_s: int = 10
    progress_percent_threshold: float = 5.0
    soc_change_threshold: float = 0.01
    temperature_change_threshold_c: float = 1.0
    compute_util_change_threshold: float = 0.05


@dataclass
class RecorderMetrics:
    events_emitted: int = 0
    events_dropped: int = 0
    snapshots_written: int = 0
    trace_bytes_written: int = 0
    profiler_wall_overhead_ns: int = 0
    flush_time_ns: int = 0
    spans: dict[str, list[int]] = field(default_factory=dict)
    categories: dict[str, int] = field(default_factory=dict)


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def provenance_hash(items: list[Any]) -> str:
    blob = json.dumps(items, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class FlightRecorder:
    def __init__(
        self,
        run_id: str | None = None,
        root: Path | None = None,
        scenario: str = "unspecified",
        workload: str = "unspecified",
        seed: int | None = None,
        config: ProfilingConfig | None = None,
        sink: TraceSink | None = None,
    ) -> None:
        self.root = root or Path.cwd()
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
        self.run_dir = self.root / "profiles" / self.run_id
        self.config = config or ProfilingConfig()
        self.scenario = scenario
        self.workload = workload
        self.seed = seed
        self._sequence = 0
        self._wall_start_ns = time.perf_counter_ns()
        self._wall_epoch_ns = time.time_ns()
        self._closed = False
        self._last_event: TraceEvent | None = None
        self._last_simulation_time_ns = 0
        self.metrics = RecorderMetrics()
        self.sink = sink or JsonlTraceSink(self.run_dir / "events.jsonl")
        self.snapshot_sink = JsonlTraceSink(self.run_dir / "snapshots.jsonl") if sink is None else InMemoryTraceSink()
        self.failures_sink = JsonlTraceSink(self.run_dir / "failures.jsonl") if sink is None else InMemoryTraceSink()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_manifest(simulation_start=None, simulation_end=None)

    @property
    def last_event_id(self) -> str | None:
        return self._last_event.header.event_id if self._last_event else None

    def emit(
        self,
        event_type: str | TraceEventType,
        simulation_time_ns: int,
        *,
        source: str = "O-SLURM",
        node_id: str | None = None,
        job_id: str | None = None,
        correlation_id: str | None = None,
        parent_event_id: str | None = None,
        payload: dict[str, Any] | None = None,
        wall_time_ns: int | None = None,
    ) -> TraceEvent:
        overhead_start = time.perf_counter_ns()
        event_value = event_type.value if isinstance(event_type, TraceEventType) else str(event_type)
        self._sequence += 1
        event_id = f"{self.run_id}:{self._sequence:012d}"
        if wall_time_ns is None:
            wall_time_ns = self._wall_epoch_ns + (time.perf_counter_ns() - self._wall_start_ns)
        category = category_for(event_value).value
        event = TraceEvent(
            schema_version=TRACE_SCHEMA_VERSION,
            header=TraceHeader(
                run_id=self.run_id,
                sequence=self._sequence,
                wall_time_ns=wall_time_ns,
                simulation_time_ns=int(simulation_time_ns),
                event_type=event_value,
                node_id=node_id,
                job_id=job_id,
                correlation_id=correlation_id,
                parent_event_id=parent_event_id,
                event_id=event_id,
            ),
            category=category,
            source=source,
            payload=payload or {},
        )
        self.sink.write_event(event)
        if category == "FAILURE" or event_value == TraceEventType.SAFETY_EVENT.value:
            self.failures_sink.write_event(event)
        self.metrics.events_emitted += 1
        self.metrics.categories[category] = self.metrics.categories.get(category, 0) + 1
        self.metrics.trace_bytes_written = self.sink.bytes_written
        self._last_event = event
        self._last_simulation_time_ns = max(self._last_simulation_time_ns, int(simulation_time_ns))
        self.metrics.profiler_wall_overhead_ns += time.perf_counter_ns() - overhead_start
        return event

    def snapshot(self, simulation_time_ns: int, state: dict[str, Any], *, source: str = "O-SLURM") -> TraceEvent:
        event = self.emit(
            TraceEventType.GLOBAL_SNAPSHOT,
            simulation_time_ns,
            source=source,
            payload={"state": state, "state_digest": digest_state(state)},
        )
        self.snapshot_sink.write_event(event)
        self.metrics.snapshots_written += 1
        return event

    @contextmanager
    def span(
        self,
        name: str,
        simulation_time_ns: int,
        *,
        source: str = "O-SLURM",
        node_id: str | None = None,
        job_id: str | None = None,
        correlation_id: str | None = None,
        parent_event_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        start = time.perf_counter_ns()
        try:
            yield
        finally:
            duration = time.perf_counter_ns() - start
            self.metrics.spans.setdefault(name, []).append(duration)
            self.emit(
                TraceEventType.PERFORMANCE_SPAN,
                simulation_time_ns,
                source=source,
                node_id=node_id,
                job_id=job_id,
                correlation_id=correlation_id,
                parent_event_id=parent_event_id,
                payload={"span": name, "duration_ns": duration, "context": context or {}},
            )

    def flush(self) -> None:
        start = time.perf_counter_ns()
        self.sink.flush()
        self.snapshot_sink.flush()
        self.failures_sink.flush()
        self.metrics.flush_time_ns += time.perf_counter_ns() - start

    def close(self, simulation_end_ns: int | None = None) -> None:
        if self._closed:
            return
        end_ns = self._last_simulation_time_ns if simulation_end_ns is None else simulation_end_ns
        self.emit(TraceEventType.SIMULATION_END, end_ns, payload={"run_id": self.run_id})
        self.flush()
        self._write_derived_outputs()
        self._write_metrics()
        self._write_manifest(simulation_start=None, simulation_end=end_ns)
        self.sink.close()
        self.snapshot_sink.close()
        self.failures_sink.close()
        self._closed = True

    def _write_manifest(self, simulation_start: str | None, simulation_end: int | None) -> None:
        manifest = {
            "run_id": self.run_id,
            "scenario": self.scenario,
            "workload": self.workload,
            "seed": self.seed,
            "gmat_version": "detected-at-runtime",
            "oslurm_git_commit": _git_commit(self.root),
            "hardware_profiles": [],
            "hardware_envelope_provenance_hash": provenance_hash([self.scenario, self.workload, self.seed]),
            "scheduler_policy": "MAXIMIZE_WORST_SAFETY_MARGIN",
            "simulation_start": simulation_start,
            "simulation_end": simulation_end,
            "profiling_config": asdict(self.config),
            "schema_version": TRACE_SCHEMA_VERSION,
        }
        (self.run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    def _write_metrics(self) -> None:
        spans = {}
        for name, values in self.metrics.spans.items():
            ordered = sorted(values)
            spans[name] = {
                "count": len(values),
                "p50_ns": percentile(ordered, 50),
                "p95_ns": percentile(ordered, 95),
                "p99_ns": percentile(ordered, 99),
            }
        data = asdict(self.metrics)
        data["spans"] = spans
        (self.run_dir / "metrics.json").write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _write_derived_outputs(self) -> None:
        try:
            from .analysis import ProfileAnalyzer

            analyzer = ProfileAnalyzer(self.run_dir)
            (self.run_dir / "bottlenecks.json").write_text(json.dumps(analyzer.bottleneck_summary(), indent=2, sort_keys=True), encoding="utf-8")
            analyzer.export_perfetto(self.run_dir / "trace.json", time_axis="wall")
            topology_epochs = [
                event.to_dict()
                for event in analyzer.events
                if event.header.event_type in {TraceEventType.TOPOLOGY_EPOCH_BEGIN.value, TraceEventType.TOPOLOGY_EPOCH_END.value}
            ]
            (self.run_dir / "topology_epochs.json").write_text(json.dumps(topology_epochs, indent=2, sort_keys=True), encoding="utf-8")
        except Exception:
            self.metrics.events_dropped += 1


def percentile(values: list[int], pct: int) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, round((pct / 100) * (len(values) - 1)))
    return int(values[index])


def digest_state(state: dict[str, Any]) -> str:
    blob = json.dumps(state, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
