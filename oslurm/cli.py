from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from .montecarlo import run_campaign
from .network import MultiConstellationRuntime
from .profile.analysis import ProfileAnalyzer, latest_profile
from .profile.recorder import FlightRecorder, ProfilingConfig
from .profile.replay import replay_trace
from .profile.session import inject_failure, run_profiled_satellite_scenario


class OslurmCli:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.recorder: FlightRecorder | None = None
        self.loaded_run_dir: Path | None = latest_profile(root)
        self.scenario = "satellite-autonomy"
        self.workload = "handoff-job-381"
        self.seed: int | None = None
        self.network = MultiConstellationRuntime(root)

    def execute(self, line: str) -> str:
        parts = shlex.split(line)
        if not parts or parts[0].startswith("#"):
            return ""
        if parts[0] == "load" and len(parts) >= 3:
            if parts[1] == "constellation" and len(parts) >= 4:
                return self.network.load_constellation(parts[2], parts[3])
            if parts[1] == "scenario":
                self.scenario = parts[2]
            if parts[1] == "workload":
                self.workload = parts[2]
            return f"loaded {parts[1]} {parts[2]}"
        if parts[0] == "connect" and len(parts) >= 4 and parts[1] == "constellations":
            return self.network.connect(parts[2], parts[3])
        if parts[0] == "submit" and len(parts) >= 3 and parts[1] == "job":
            if self.recorder is None:
                self.recorder = FlightRecorder(root=self.root, scenario=self.scenario, workload=parts[2], seed=self.seed, config=ProfilingConfig(mode="full", trace=True))
                self.loaded_run_dir = self.recorder.run_dir
            return self.network.submit_job(parts[2], self.recorder)
        if parts[0] == "show":
            return self._show(parts[1:])
        if parts[0] == "transfer" and len(parts) >= 2 and parts[1] == "submit":
            return self.network.transfer_submit(parts[2:], self.recorder)
        if parts[0] == "scheduler":
            return self._scheduler(parts[1:])
        if parts[0] == "visibility" and len(parts) >= 4 and parts[1] == "check":
            return self.network.visibility_check(parts[2], parts[3])
        if parts[0] == "topology" and len(parts) >= 4 and parts[1] == "explain-link":
            return self.network.explain_link(parts[2], parts[3])
        if parts[0] == "seed" and len(parts) >= 2:
            self.seed = int(parts[1])
            return f"seed {self.seed}"
        if parts[0] == "run":
            return self._run(parts[1:] or ["satellite-demo"])
        if parts[0] == "profile":
            return self._profile(parts[1:])
        if parts[0] == "montecarlo":
            return self._montecarlo(parts[1:])
        if parts[0] == "inject":
            return self._inject(parts[1:])
        if parts[0] == "state":
            return self._state(parts[1:])
        return f"unknown command: {parts[0]}"

    def _profile(self, args: list[str]) -> str:
        if not args:
            return "usage: profile <on|off|reset|status|summary|topology|scheduler|node|job|bottleneck|failures|export|replay|timeline|cause|load>"
        command = args[0]
        if command == "on":
            run_id = option(args, "--run-id") or None
            mode = option(args, "--mode") or "light"
            trace = "--trace" in args
            self.recorder = FlightRecorder(run_id=run_id, root=self.root, scenario=self.scenario, workload=self.workload, seed=self.seed, config=ProfilingConfig(mode=mode, trace=trace))
            self.loaded_run_dir = self.recorder.run_dir
            return f"profile on run_id={self.recorder.run_id} mode={mode}"
        if command == "off":
            if self.recorder:
                self.recorder.close()
                run_dir = self.recorder.run_dir
                self.recorder = None
                self.loaded_run_dir = run_dir
                return f"profile off run_dir={run_dir}"
            return "profile already off"
        if command == "reset":
            self.recorder = None
            self.loaded_run_dir = None
            return "profile reset"
        if command == "status":
            if self.recorder:
                return f"profile active run_id={self.recorder.run_id} events={self.recorder.metrics.events_emitted}"
            return f"profile inactive loaded={self.loaded_run_dir or 'none'}"
        if command == "load" and len(args) >= 2:
            path = Path(args[1])
            self.loaded_run_dir = path if path.is_absolute() else self.root / "profiles" / args[1]
            return f"profile loaded {self.loaded_run_dir}"
        if command == "replay":
            run_dir = Path(args[1]) if len(args) >= 2 else self._run_dir()
            result = replay_trace(run_dir)
            return json.dumps(result.__dict__, indent=2, sort_keys=True)
        if self.recorder:
            self.recorder.flush()
            self.recorder._write_metrics()
        analyzer = ProfileAnalyzer(self._run_dir())
        if command == "summary":
            return format_summary(analyzer.summary())
        if command == "network":
            return format_mapping("NETWORK", analyzer.network_metrics())
        if command == "topology":
            return format_mapping("TOPOLOGY", analyzer.topology_metrics())
        if command == "scheduler":
            return format_mapping("SCHEDULER", analyzer.scheduler_metrics())
        if command == "node" and len(args) >= 2:
            return "\n".join(analyzer.timeline(args[1])) or f"no node history for {args[1]}"
        if command == "job" and len(args) >= 2:
            return format_mapping(args[1], analyzer.job_report(args[1]))
        if command == "timeline" and len(args) >= 2:
            return "\n".join(analyzer.timeline(args[1])) or f"no timeline for {args[1]}"
        if command == "cause" and len(args) >= 2:
            return "\n↓\n".join(analyzer.cause(args[1])) or f"no causal chain for {args[1]}"
        if command == "bottleneck":
            if len(args) >= 2 and args[1] in {"network", "joint"}:
                data = analyzer.bottleneck_summary()
                network = analyzer.network_metrics()
                return format_mapping(f"BOTTLENECK {args[1].upper()}", {**data, **network})
            if len(args) >= 2 and args[1] == "constellation":
                return format_constellation(analyzer)
            return format_mapping("BOTTLENECK", analyzer.bottleneck_summary())
        if command == "failures":
            return json.dumps(analyzer.failures(), indent=2, sort_keys=True)
        if command == "visibility-invariants":
            violations = analyzer.visibility_invariant_violations()
            return json.dumps(violations, indent=2, sort_keys=True) if violations else "visibility invariants: PASS"
        if command == "export":
            return self._export(analyzer, args[1:])
        return f"unknown profile command: {command}"

    def _run(self, args: list[str]) -> str:
        if args and args[0][-1:] in {"h", "m", "s"}:
            return self.network.run(args[0], self.recorder)
        if self.recorder is None:
            self.recorder = FlightRecorder(root=self.root, scenario=self.scenario, workload=self.workload, seed=self.seed, config=ProfilingConfig(mode="full", trace=True))
            self.loaded_run_dir = self.recorder.run_dir
        result = run_profiled_satellite_scenario(self.recorder, self.root)
        return f"run complete job={result['job_id']} profile={self.recorder.run_dir}"

    def _show(self, args: list[str]) -> str:
        if not args:
            return "usage: show constellations|network|contacts|transfers|reservations"
        if args[0] == "constellations":
            return self.network.show_constellations()
        if args[0] == "constellation" and len(args) >= 2:
            item = self.network.constellations.get(args[1])
            return json.dumps(item.__dict__, default=str, indent=2, sort_keys=True) if item else f"missing constellation {args[1]}"
        if args[0] == "network":
            return self.network.show_network(args[1] if len(args) >= 2 else None)
        if args[0] == "contacts" and len(args) >= 2:
            return self.network.show_contacts(args[1])
        if args[0] == "transfers":
            return self.network.show_transfers()
        if args[0] == "reservations":
            return self.network.show_reservations()
        return f"unknown show command: {args[0]}"

    def _scheduler(self, args: list[str]) -> str:
        if len(args) >= 2 and args[0] == "show" and args[1] == "comm":
            node = args[2] if len(args) >= 3 else ""
            return self.network.show_contacts(node) if node else self.network.show_network("comm")
        if len(args) >= 3 and args[0] == "explain" and args[1] == "transfer":
            plan = self.network.transfers.get(args[2])
            return json.dumps(plan.as_dict(), indent=2, sort_keys=True) if plan else f"missing transfer {args[2]}"
        if len(args) >= 2 and args[0] == "routes":
            plan = self.network.transfers.get(args[1])
            if not plan:
                return f"missing transfer {args[1]}"
            return "\n".join(f"{hop.source}->{hop.destination} {hop.contact_id} T+{hop.start_s:.1f}-{hop.end_s:.1f}s" for hop in plan.hops)
        return "usage: scheduler show comm <node> | scheduler explain transfer <id> | scheduler routes <id>"

    def _inject(self, args: list[str]) -> str:
        if self.recorder is None:
            return "profile is not active"
        if len(args) >= 5 and args[0] == "failure" and args[1] == "node":
            at = float(args[4].lstrip("+").rstrip("s")) if args[3] == "at" else 0.0
            event = inject_failure(self.recorder, failure_type="NODE_LOSS", target=args[2], at_s=at, severity="HIGH", seed=self.seed)
            return f"injected {event.header.event_id}"
        return "usage: inject failure node SAT17 at +300s"

    def _montecarlo(self, args: list[str]) -> str:
        if len(args) >= 2 and args[0] == "run":
            scenario = args[1]
            runs = int(option(args, "--runs") or 10)
            seed = int(option(args, "--seed") or 42)
            campaign = run_campaign(self.root, scenario, runs, seed)
            return f"montecarlo campaign {campaign}"
        if args and args[0] == "worst":
            mc_dir = self.root / "mc"
            campaigns = [p for p in mc_dir.iterdir() if (p / "summary.json").exists()] if mc_dir.exists() else []
            if not campaigns:
                return "no campaigns"
            latest = max(campaigns, key=lambda p: (p / "summary.json").stat().st_mtime)
            summary = json.loads((latest / "summary.json").read_text(encoding="utf-8"))
            return json.dumps(summary.get("worst_runs", {}), indent=2, sort_keys=True)
        return "usage: montecarlo run <scenario> --runs N --seed S"

    def _state(self, args: list[str]) -> str:
        if not args:
            return "usage: state node SAT17 | state job JOB381 | state topology"
        if args[0] == "topology":
            return "live topology: SAT01-SAT02 SAT01-SAT03 SAT03-SAT04"
        if len(args) >= 2:
            return f"live {args[0]} {args[1]}: no active simulator attached"
        return "state command incomplete"

    def _export(self, analyzer: ProfileAnalyzer, args: list[str]) -> str:
        if not args:
            return "usage: profile export <path>|node SAT --format csv|job JOB --format csv"
        if args[0] == "node" and len(args) >= 2:
            output = self.root / f"{args[1]}-node-history.csv"
            analyzer.export_node_csv(args[1], output)
            return f"exported {output}"
        if args[0] == "job" and len(args) >= 2:
            output = self.root / f"{args[1]}-job-history.csv"
            analyzer.export_job_csv(args[1], output)
            return f"exported {output}"
        output = Path(args[0])
        if not output.is_absolute():
            output = self.root / output
        axis = option(args, "--time-axis") or "wall"
        analyzer.export_perfetto(output, time_axis=axis)
        return f"exported {output}"

    def _run_dir(self) -> Path:
        run_dir = self.loaded_run_dir or latest_profile(self.root)
        if run_dir is None:
            raise RuntimeError("no profile run loaded")
        return run_dir


def option(args: list[str], name: str) -> str | None:
    if name not in args:
        return None
    index = args.index(name)
    return args[index + 1] if index + 1 < len(args) else None


def format_mapping(title: str, data: dict) -> str:
    return title + "\n" + "\n".join(f"{key}: {value}" for key, value in data.items())


def format_summary(data: dict) -> str:
    return "\n".join([
        "RUN",
        f"run_id: {data['run_id']}",
        f"scenario: {data['scenario']}",
        f"simulated duration: {data['simulated_duration_s']:.3f}s",
        f"wall duration: {data['wall_duration_s']:.3f}s",
        "",
        "EVENTS",
        f"total: {data['events']['total']}",
        "",
        "COMPUTE",
        f"utilization: {data['compute']['aggregate_compute_utilization']:.3f}",
        f"stranded compute: {data['compute']['stranded_compute']:.3f}",
        "",
        "TOPOLOGY",
        f"epochs: {data['topology']['epochs']}",
        f"partitions: {data['topology']['component_splits']}",
        f"edge churn: {data['topology']['topology_changes']}",
        "",
        "SCHEDULER",
        f"decisions: {data['scheduler']['decisions']}",
        f"p95 ns: {data['scheduler']['p95_ns']}",
        "",
        "JOBS",
        f"completion: {data['jobs']['completed']}/{data['jobs']['total']}",
        f"deadline misses: {data['jobs']['deadline_misses']}",
        f"migrations: {data['jobs']['migrations']}",
        "",
        "SAFETY",
        f"energy violations: {data['safety']['energy_violations']}",
        f"thermal violations: {data['safety']['thermal_violations']}",
        "",
        "BOTTLENECK",
        f"dominant constellation bottleneck: {data['bottleneck']}",
        f"network transfer plans: {data['network']['transfer_plans']}",
        f"network placement changes: {data['network']['network_changed_compute_placements']}",
        "",
        "TRACE",
        f"events written: {data['trace']['events_written']}",
        f"bytes: {data['trace']['bytes']}",
        f"profiler overhead ns: {data['trace']['profiler_overhead_ns']}",
    ])


def format_constellation(analyzer: ProfileAnalyzer) -> str:
    sched = analyzer.scheduler_metrics()
    bottleneck = analyzer.bottleneck_summary()
    topo = analyzer.topology_metrics()
    return "\n".join([
        "CONSTELLATION BOTTLENECKS",
        "",
        "Candidate rejection:",
        *[f"{key.lower():24s} {value:.1f}%" for key, value in sched["candidate_rejection"].items()],
        "",
        "Job-delay attribution:",
        *[f"{key.lower():24s} {value:.1f}%" for key, value in bottleneck["percentages"].items()],
        "",
        "Topology churn:",
        f"epochs                   {topo['epochs']}",
        f"meaningful changes       {topo['topology_changes']}",
        f"no-op recomputes         {round(topo['reevaluation_no_op_ratio'] * max(1, topo['scheduler_reevaluations']))}",
        "",
        "Control-plane:",
        f"decision amplification   {topo['decision_amplification']:.3f}",
        f"migration amplification  {topo['migration_amplification']:.3f}",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oslurm")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    cli = OslurmCli(Path.cwd())
    lines = [" ".join(args.command)] if args.command else sys.stdin.read().splitlines()
    for line in lines:
        if not line.strip():
            continue
        try:
            output = cli.execute(line)
        except Exception as exc:
            print(f"ERROR: {exc}")
            return 1
        if output:
            print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
