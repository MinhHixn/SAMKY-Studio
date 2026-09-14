#!/usr/bin/env python3
"""Headless client for the MiroFish Studio HTTP API.

The CLI deliberately uses the public API instead of importing application internals, so the
same command works against a local Docker stack or a remotely hosted MiroFish instance.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import requests


TERMINAL_TASK_STATES = {"completed", "failed"}
TERMINAL_RUN_STATES = {"completed", "failed", "stopped", "paused"}


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def request(self, method: str, path: str, **kwargs) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise ApiError(f"Cannot reach MiroFish at {self.base_url}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ApiError(f"MiroFish returned HTTP {response.status_code} without JSON") from exc

        if not response.ok or payload.get("success") is False:
            message = payload.get("error") or payload.get("message") or f"HTTP {response.status_code}"
            raise ApiError(str(message))
        return payload

    def get(self, path: str) -> dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", path, json=body)


def note(message: str, *, quiet: bool = False) -> None:
    if not quiet:
        print(f"[sam] {message}", file=sys.stderr, flush=True)


def wait_for_task(client: Client, path: str, poll_body: dict[str, Any] | None, interval: float, quiet: bool) -> dict[str, Any]:
    last_message = None
    while True:
        payload = client.post(path, poll_body) if poll_body is not None else client.get(path)
        data = payload.get("data") or {}
        status = str(data.get("status", "")).lower()
        message = data.get("message")
        if message and message != last_message:
            progress = data.get("progress")
            suffix = f" ({progress}%)" if progress is not None else ""
            note(f"{message}{suffix}", quiet=quiet)
            last_message = message
        if status in TERMINAL_TASK_STATES or data.get("already_prepared"):
            if status == "failed":
                raise ApiError(data.get("error") or data.get("message") or "Background task failed")
            return data
        time.sleep(interval)


def doctor(client: Client, as_json: bool = False) -> int:
    data = client.get("/api/status").get("data") or {}
    runtime = data.get("runtime") or data.get("ollama") or {}
    result = {
        "ready": bool(runtime.get("reachable") and data.get("neo4j", {}).get("connected")),
        "runtime": runtime,
        "neo4j": data.get("neo4j"),
        "disk": data.get("disk"),
    }
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Model runtime : {'ready' if runtime.get('reachable') else 'not ready'} ({runtime.get('model') or runtime.get('model_configured') or 'unknown'})")
        print(f"Neo4j        : {'ready' if data.get('neo4j', {}).get('connected') else 'not ready'}")
        print(f"Overall      : {'READY' if result['ready'] else 'SETUP REQUIRED'}")
    return 0 if result["ready"] else 2


def run_event(args: argparse.Namespace) -> int:
    client = Client(args.base_url, args.timeout)
    paths = [Path(item).expanduser().resolve() for item in args.file]
    invalid = [path for path in paths if not path.is_file()]
    if invalid:
        raise ApiError(f"Input file does not exist: {invalid[0]}")

    if not args.skip_health:
        status = client.get("/api/status").get("data") or {}
        runtime = status.get("runtime") or status.get("ollama") or {}
        if not runtime.get("reachable") or not status.get("neo4j", {}).get("connected"):
            raise ApiError("Model runtime or Neo4j is not ready. Run `mirofish_cli.py doctor` for details.")

    note("Uploading sources and generating the event ontology…", quiet=args.quiet)
    with ExitStack() as stack:
        uploads = [
            ("files", (path.name, stack.enter_context(path.open("rb")), "application/octet-stream"))
            for path in paths
        ]
        fields = {
            "simulation_requirement": args.goal,
            "project_name": args.name or paths[0].stem,
        }
        ontology = client.request("POST", "/api/graph/ontology/generate", data=fields, files=uploads)
    project_id = ontology["data"]["project_id"]

    note("Building the knowledge graph…", quiet=args.quiet)
    graph_task = client.post("/api/graph/build", {"project_id": project_id})["data"]["task_id"]
    wait_for_task(client, f"/api/graph/task/{graph_task}", None, args.poll_interval, args.quiet)
    project = client.get(f"/api/graph/project/{project_id}")["data"]
    graph_id = project.get("graph_id")
    if not graph_id:
        raise ApiError("Knowledge graph finished without returning a graph_id")

    note("Creating and preparing the agent society…", quiet=args.quiet)
    created = client.post(
        "/api/simulation/create",
        {
            "project_id": project_id,
            "graph_id": graph_id,
            "enable_twitter": args.platform in {"twitter", "parallel"},
            "enable_reddit": args.platform in {"reddit", "parallel"},
        },
    )["data"]
    simulation_id = created["simulation_id"]
    prepared = client.post(
        "/api/simulation/prepare",
        {
            "simulation_id": simulation_id,
            "use_llm_for_profiles": True,
            "parallel_profile_count": args.profile_workers,
        },
    )["data"]
    if not prepared.get("already_prepared") and str(prepared.get("status", "")).lower() not in {"ready", "completed"}:
        wait_for_task(
            client,
            "/api/simulation/prepare/status",
            {"task_id": prepared.get("task_id"), "simulation_id": simulation_id},
            args.poll_interval,
            args.quiet,
        )

    note("Starting simulation…", quiet=args.quiet)
    started = client.post(
        "/api/simulation/start",
        {
            "simulation_id": simulation_id,
            "platform": args.platform,
            "max_rounds": args.rounds,
            "enable_graph_memory_update": args.graph_memory,
            "force": args.force,
        },
    )["data"]

    result: dict[str, Any] = {
        "project_id": project_id,
        "graph_id": graph_id,
        "simulation_id": simulation_id,
        "status": started.get("runner_status", "running"),
    }

    if args.wait:
        last_round = None
        while True:
            run_state = client.get(f"/api/simulation/{simulation_id}/run-status")["data"]
            current_round = run_state.get("current_round")
            if current_round != last_round:
                note(
                    f"Round {current_round or 0}/{run_state.get('total_rounds') or args.rounds} · {run_state.get('total_actions_count', 0)} actions",
                    quiet=args.quiet,
                )
                last_round = current_round
            run_status = str(run_state.get("runner_status", "")).lower()
            if run_status in TERMINAL_RUN_STATES:
                result["status"] = run_status
                result["run"] = run_state
                if run_status == "failed":
                    raise ApiError(run_state.get("error") or "Simulation failed")
                break
            time.sleep(args.poll_interval)

        if args.report:
            note("Generating report…", quiet=args.quiet)
            report = client.post("/api/report/generate", {"simulation_id": simulation_id})["data"]
            if str(report.get("status", "")).lower() != "completed":
                report = wait_for_task(
                    client,
                    "/api/report/generate/status",
                    {"task_id": report.get("task_id"), "simulation_id": simulation_id},
                    args.poll_interval,
                    args.quiet,
                )
            result["report_id"] = report.get("report_id")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SAMKY Studio without the web UI")
    parser.add_argument("--base-url", default="http://localhost:5001", help="SAMKY Studio API base URL")
    parser.add_argument("--timeout", type=float, default=300.0, help="HTTP timeout in seconds")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_parser = subparsers.add_parser("doctor", help="Check model, Neo4j and storage readiness")
    doctor_parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    run_parser = subparsers.add_parser("run", help="Create and start one event simulation")
    run_parser.add_argument("--file", action="append", required=True, help="PDF, Markdown or TXT source; repeat for multiple files")
    run_parser.add_argument("--goal", required=True, help="Question or outcome the simulation should investigate")
    run_parser.add_argument("--name", help="Human-readable event name")
    run_parser.add_argument("--platform", choices=["parallel", "twitter", "reddit"], default="parallel")
    run_parser.add_argument("--rounds", type=int, default=10)
    run_parser.add_argument("--profile-workers", type=int, default=5)
    run_parser.add_argument("--graph-memory", action="store_true")
    run_parser.add_argument("--force", action="store_true", help="Force restart if prior runtime artifacts exist")
    run_parser.add_argument("--wait", action="store_true", help="Wait until the simulation finishes")
    run_parser.add_argument("--report", action="store_true", help="Generate a report after completion; implies --wait")
    run_parser.add_argument("--skip-health", action="store_true", help="Attempt the run even if the health check is degraded")
    run_parser.add_argument("--poll-interval", type=float, default=3.0)
    run_parser.add_argument("--quiet", action="store_true", help="Only print the final JSON result")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "doctor":
        return doctor(Client(args.base_url, args.timeout), args.json)
    if args.command == "run":
        if args.rounds < 1:
            parser.error("--rounds must be at least 1")
        if args.report:
            args.wait = True
        return run_event(args)
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
