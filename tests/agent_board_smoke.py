#!/usr/bin/env python3
"""Registered Tier-1 entrypoint for A0 planning and canonical materialization."""
from control_plane_agent_contract_smoke import main as planning_main
from system_state_materializer_smoke import main as state_main

if __name__ == '__main__':
    planning_result = planning_main()
    state_result = state_main()
    raise SystemExit(max(planning_result, state_result))
