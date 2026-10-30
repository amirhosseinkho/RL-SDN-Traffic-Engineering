"""Client for the REST API of emulation/controller_app.py, plus starting the controller process."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.controller.flow_rules import Hop

APP = Path(__file__).resolve().parent / "controller_app.py"


class ControllerClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{method} {path}: {e.code} {e.read().decode(errors='replace')}") from e

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def topology(self) -> dict[str, Any]:
        return self._request("GET", "/topology")

    def port_stats(self) -> dict[tuple[int, int], dict[str, Any]]:
        return {(p["dpid"], p["port_no"]): p for p in self._request("GET", "/stats/ports")["ports"]}

    def paths(self) -> dict[str, Any]:
        return self._request("GET", "/paths")

    def install_path(self, flow_id: int, src_ip: str, dst_ip: str, hops: list[Hop], reverse: bool = False) -> dict[str, Any]:
        return self._request(
            "POST",
            "/paths",
            {"flow_id": flow_id, "reverse": reverse, "src_ip": src_ip, "dst_ip": dst_ip,
             "hops": [[h.dpid, h.out_port] for h in hops]},
        )

    def clear_paths(self) -> dict[str, Any]:
        return self._request("DELETE", "/paths")

    def wait_for(self, num_switches: int, num_links: int, timeout: float = 60.0) -> dict[str, Any]:
        """Wait until all switches are connected and LLDP has found all (directed) links."""
        deadline = time.time() + timeout
        topo: dict[str, Any] = {}
        while time.time() < deadline:
            try:
                topo = self.topology()
                if len(topo["connected"]) >= num_switches and len(topo["links"]) >= num_links:
                    return topo
            except (urllib.error.URLError, ConnectionError, RuntimeError):
                pass
            time.sleep(0.5)
        raise TimeoutError(f"controller saw {topo} after {timeout}s")


def controller_command() -> list[str]:
    """osken-manager if installed, else ryu-manager (or EMU_CONTROLLER_CMD, e.g. a venv's ryu-manager)."""
    custom = os.environ.get("EMU_CONTROLLER_CMD")
    if custom:
        return custom.split()
    for name in ("osken-manager", "ryu-manager"):
        exe = shutil.which(name)
        if exe:
            return [exe]
    raise FileNotFoundError("neither osken-manager nor ryu-manager is on PATH")


def start_controller(log_path: Path, rest_port: int = 8080, of_port: int = 6653) -> subprocess.Popen:
    cmd = controller_command() + ["--observe-links", "--ofp-tcp-listen-port", str(of_port), str(APP)]
    env = {**os.environ, "EMU_REST_PORT": str(rest_port)}
    log = open(log_path, "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
    client = ControllerClient(f"http://127.0.0.1:{rest_port}")
    deadline = time.time() + 30
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"controller exited with {proc.returncode}; see {log_path}")
        try:
            client.health()
            return proc
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.3)
    proc.terminate()
    raise TimeoutError(f"controller REST API did not come up; see {log_path}")
