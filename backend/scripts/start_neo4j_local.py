"""Start or reuse a local Neo4j instance for development runs."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from typing import Sequence

from neo4j import GraphDatabase


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        capture_output=True,
    )


def _docker_ready() -> bool:
    result = _run(["docker", "version"])
    return result.returncode == 0


def _start_docker_desktop() -> None:
    if sys.platform != "win32":
        return
    docker_desktop = os.path.join("C:\\", "Program Files", "Docker", "Docker", "Docker Desktop.exe")
    if not os.path.exists(docker_desktop):
        return
    subprocess.Popen([docker_desktop], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603,S607


def _wait_for_docker(timeout_seconds: int) -> bool:
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        if _docker_ready():
            return True
        time.sleep(3)
    return False


def _container_exists(name: str) -> bool:
    result = _run(["docker", "ps", "-a", "--format", "{{.Names}}"])
    if result.returncode != 0:
        return False
    names = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return name in names


def _container_running(name: str) -> bool:
    result = _run(["docker", "ps", "--format", "{{.Names}}"])
    if result.returncode != 0:
        return False
    names = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    return name in names


def _ensure_container(name: str, image: str, auth: str) -> None:
    if _container_exists(name):
        if _container_running(name):
            print(f"Neo4j container already running: {name}")
            return
        result = _run(["docker", "start", name])
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "docker start failed").strip())
        print(f"Neo4j container started: {name}")
        return

    result = _run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "-p",
            "7474:7474",
            "-p",
            "7687:7687",
            "-e",
            f"NEO4J_AUTH={auth}",
            image,
        ]
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "docker run failed").strip())
    print(f"Neo4j container created: {name}")


def _wait_for_neo4j(uri: str, user: str, password: str, timeout_seconds: int) -> bool:
    deadline = time.time() + max(1, timeout_seconds)
    while time.time() < deadline:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        try:
            driver.verify_connectivity()
            return True
        except Exception:
            time.sleep(2)
        finally:
            driver.close()
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Start local Neo4j for dev/benchmark runs")
    parser.add_argument("--container-name", default=os.environ.get("NEO4J_DOCKER_CONTAINER_NAME", "mirofish-neo4j"))
    parser.add_argument("--image", default=os.environ.get("NEO4J_DOCKER_IMAGE", "neo4j:5.15-community"))
    parser.add_argument("--auth", default=f"{os.environ.get('NEO4J_USER', 'neo4j')}/{os.environ.get('NEO4J_PASSWORD', 'mirofish')}")
    parser.add_argument("--uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD", "mirofish"))
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument("--start-docker-desktop", action="store_true", default=True)
    parser.add_argument("--no-start-docker-desktop", dest="start_docker_desktop", action="store_false")
    args = parser.parse_args()

    if shutil.which("docker") is None:
        print("Docker CLI not found in PATH.")
        return 1

    if not _docker_ready():
        if args.start_docker_desktop:
            _start_docker_desktop()
        if not _wait_for_docker(timeout_seconds=min(args.wait_seconds, 120)):
            print("Docker daemon not ready.")
            return 1

    try:
        _ensure_container(args.container_name, args.image, args.auth)
    except Exception as exc:  # noqa: BLE001
        print(f"Failed to ensure Neo4j container: {exc}")
        return 1

    if not _wait_for_neo4j(args.uri, args.user, args.password, timeout_seconds=args.wait_seconds):
        print("Neo4j did not become ready before timeout.")
        return 1

    print(f"Neo4j ready at {args.uri}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
