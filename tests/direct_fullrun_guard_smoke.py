#!/usr/bin/env python3
"""The pipeline module must fail closed without two explicit fullrun opts."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from run_local import install_bound_input_network_guard  # noqa: E402


def test_direct_module_execution_is_blocked_by_default() -> None:
    env = os.environ.copy()
    env.pop("R1000_ALLOW_DIRECT_FULLRUN", None)
    result = subprocess.run(
        [sys.executable, str(ROOT / "r1000_pipeline.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2
    assert "direct full pipeline blocked" in result.stderr


def test_bound_input_guard_blocks_post_binding_network_access() -> None:
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    sock = socket.socket()
    try:
        install_bound_input_network_guard()
        try:
            sock.connect(("127.0.0.1", 9))
        except RuntimeError as exc:
            assert "runtime inputs were hash-bound" in str(exc)
        else:
            raise AssertionError("bound-input network guard did not block connect")
    finally:
        sock.close()
        socket.create_connection = original_create_connection
        socket.socket.connect = original_connect
        socket.socket.connect_ex = original_connect_ex


if __name__ == "__main__":
    test_direct_module_execution_is_blocked_by_default()
    test_bound_input_guard_blocks_post_binding_network_access()
    print("direct_fullrun_guard_smoke: PASS")
