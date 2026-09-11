#!/usr/bin/env python3
"""Create temporary research-only transport configuration without logging secrets."""
import configparser
import json
import os
from pathlib import Path
import re
import sys


def configure():
    from tools.macro_history_sources import require
    from tools.macro_research_checkpoint import safe_path
    os.umask(0o077)
    lane = os.environ["MACRO_RESEARCH_LANE"]
    require(re.fullmatch(r"scheduled|pr-[1-9][0-9]*", lane), "research_lane")
    temp = safe_path(os.environ["RUNNER_TEMP"])
    conf = configparser.ConfigParser(interpolation=None)
    text = os.environ.get("MACRO_DRIVE_CONFIG")
    account = os.environ.get("MACRO_DRIVE_SERVICE_ACCOUNT")
    require(bool(text or account), "research_drive_credentials_unavailable")
    if text:
        supplied = configparser.ConfigParser(interpolation=None)
        supplied.read_string(text)
        require(supplied.has_section("gdrive") and supplied["gdrive"].get("type") == "drive", "research_drive_config")
        conf["gdrive"] = dict(supplied["gdrive"])
    else:
        payload = json.loads(account)
        require(payload.get("type") == "service_account", "research_drive_account")
        account_path = temp / "macro-drive-account.json"
        with account_path.open("x") as handle:
            handle.write(account)
        conf["gdrive"] = dict(type="drive", scope="drive", service_account_file=str(account_path))
    root_id = os.environ.get("MACRO_DRIVE_ROOT_FOLDER_ID")
    if root_id:
        require(re.fullmatch(r"[A-Za-z0-9_-]+", root_id), "research_drive_root_id")
        conf["gdrive"]["root_folder_id"] = root_id
    # A rooted remote and an unrooted remote use different existing repository bases.
    prefix = "gdrive:" if conf["gdrive"].get("root_folder_id") else "gdrive:r1000_top30_institutional/"
    config_path = temp / "macro-rclone.conf"
    with config_path.open("x") as handle:
        conf.write(handle)
    output = "MACRO_RCLONE_CONFIG=" + str(config_path) + "\n"
    output += "MACRO_RESEARCH_REMOTE=" + prefix + "research/macro_technical_evidence/v1/" + lane + "\n"
    with open(os.environ["GITHUB_ENV"], "a") as handle:
        handle.write(output)
    print("Research transport configured; credentials are not part of the checkpoint.")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        configure()
    except Exception:
        raise SystemExit("BLOCKED_RESEARCH_DRIVE_CONFIGURATION") from None
