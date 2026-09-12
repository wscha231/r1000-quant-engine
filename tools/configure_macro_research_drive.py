#!/usr/bin/env python3
"""Create temporary research-only transport configuration without logging secrets."""
import configparser
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys


SAFE_DIAGNOSTIC_CODES = {
    "CREDENTIALS_MISSING", "INVALID_CONFIG", "OAUTH_CLIENT_PAIR_INCOMPLETE",
    "OAUTH_CLIENT_ID_FORMAT", "OAUTH_PLACEHOLDER", "OAUTH_TOKEN_MISSING",
    "OAUTH_TOKEN_JSON", "OAUTH_ACCESS_TOKEN_MISSING", "OAUTH_REFRESH_TOKEN_MISSING",
    "OAUTH_FIELD_FORMAT", "OAUTH_EXPIRY_FORMAT",
}


class DriveConfigurationError(ValueError):
    def __init__(self, code):
        # Even an accidental caller-supplied value cannot enter a diagnostic.
        super().__init__(code if code in SAFE_DIAGNOSTIC_CODES else "INVALID_CONFIG")


def validate_drive_config(remote):
    """Check rclone's credential shape locally; this does not prove Google access."""
    if remote.get("service_account_file") or remote.get("service_account_credentials"):
        return
    client_id = remote.get("client_id", "")
    client_secret = remote.get("client_secret", "")
    if bool(client_id) != bool(client_secret):
        raise DriveConfigurationError("OAUTH_CLIENT_PAIR_INCOMPLETE")
    raw = remote.get("token")
    if not raw:
        raise DriveConfigurationError("OAUTH_TOKEN_MISSING")
    try:
        token = json.loads(raw)
    except (ValueError, TypeError):
        raise DriveConfigurationError("OAUTH_TOKEN_JSON") from None
    if not isinstance(token, dict):
        raise DriveConfigurationError("OAUTH_TOKEN_JSON")
    # rclone also reads its legacy token object. Do not mix the two schemas:
    # an empty snake_case access_token enters rclone's legacy-token fallback.
    keys = ("access_token", "refresh_token", "expiry") if "access_token" in token else ("AccessToken", "RefreshToken", "Expiry")
    access, refresh, expiry = (token.get(key) for key in keys)
    for value, missing in ((access, "OAUTH_ACCESS_TOKEN_MISSING"), (refresh, "OAUTH_REFRESH_TOKEN_MISSING")):
        if value is None or value == "":
            raise DriveConfigurationError(missing)
    for value in (client_id, client_secret, access, refresh):
        if not isinstance(value, str) or any(c.isspace() for c in value):
            raise DriveConfigurationError("OAUTH_FIELD_FORMAT")
        if value.upper().startswith("YOUR_") or (value.startswith("<") and value.endswith(">")):
            raise DriveConfigurationError("OAUTH_PLACEHOLDER")
    # Empty custom credentials use rclone's built-in OAuth client.
    if client_id and not re.fullmatch(r"[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", client_id):
        raise DriveConfigurationError("OAUTH_CLIENT_ID_FORMAT")
    # Google access tokens expire. `expires_in` alone is not rclone's expiry.
    # A deliberately past RFC3339 expiry is valid and forces a refresh.
    if not isinstance(expiry, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", expiry
    ):
        raise DriveConfigurationError("OAUTH_EXPIRY_FORMAT")
    try:
        datetime.fromisoformat(expiry)
    except ValueError:
        raise DriveConfigurationError("OAUTH_EXPIRY_FORMAT") from None


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
    if not (text or account):
        raise DriveConfigurationError("CREDENTIALS_MISSING")
    if text:
        supplied = configparser.ConfigParser(interpolation=None)
        try:
            supplied.read_string(text)
        except configparser.Error:
            raise DriveConfigurationError("INVALID_CONFIG") from None
        if not (supplied.has_section("gdrive") and supplied["gdrive"].get("type") == "drive"):
            raise DriveConfigurationError("INVALID_CONFIG")
        validate_drive_config(supplied["gdrive"])
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
    print("Research transport configuration shape accepted; Google access is not yet verified.")


def main():
    try:
        configure()
    except DriveConfigurationError as exc:
        raise SystemExit("BLOCKED_RESEARCH_DRIVE_CONFIGURATION:" + str(exc)) from None
    except Exception:
        raise SystemExit("BLOCKED_RESEARCH_DRIVE_CONFIGURATION") from None


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
