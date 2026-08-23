#!/usr/bin/env python3
"""
campwatch -- personal ReserveCalifornia cancellation scanner.

Usage:
    python campwatch.py lookup "Pfeiffer Big Sur"       # find place + facility IDs
    python campwatch.py run --config config.yaml        # continuous mode (VPS/Pi/always-on machine)
    python campwatch.py run-once --config config.yaml   # single pass (GitHub Actions / any external cron)
    python campwatch.py test-notify --config config.yaml

Two run modes:
- `run`: a persistent loop, for a machine that stays on (VPS, Raspberry Pi).
- `run-once`: a single pass that exits immediately, for schedulers that only
  invoke the process periodically (GitHub Actions, cron, Task Scheduler).
  Both modes share the same per-watch timing logic, persisted to state_file,
  so run-once is safe to invoke from a scheduler on any cadence -- each watch
  independently decides whether it's actually due, using its own interval.

Design notes:
- Coverage watches (broad, many parks) and targeted watches (narrow, one
  trip) are polled on independent schedules, because they have very
  different urgency-vs-request-volume tradeoffs.
- Outside your configured active hours, the scanner does nothing (no API
  calls at all) instead of polling and queuing alerts you can't act on yet.
- State (dedup + per-watch last-checked time) persists to disk so restarts,
  or a fresh GitHub Actions runner every 5 minutes, don't cause duplicate
  notifications or reset all timers to zero.
- This only reads public availability data and links you to the official
  booking page -- it never submits a reservation or payment.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
import yaml
from zoneinfo import ZoneInfo

import notifier
import rc_client

logger = logging.getLogger("campwatch")


# --------------------------------------------------------------------------
# Config / time helpers
# --------------------------------------------------------------------------

def load_config(path: str) -> dict[str, Any]:
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return apply_env_overrides(cfg)


def apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """Let secrets be injected via environment variables (e.g. GitHub Actions
    Secrets) instead of living in the committed config.yaml. Any value not
    provided via env falls back to whatever is in the YAML file."""
    n = cfg.setdefault("notifications", {})

    email = n.setdefault("email", {})
    if os.environ.get("CAMPWATCH_EMAIL_PASSWORD"):
        email["from_password"] = os.environ["CAMPWATCH_EMAIL_PASSWORD"]
    if os.environ.get("CAMPWATCH_EMAIL_FROM"):
        email["from_address"] = os.environ["CAMPWATCH_EMAIL_FROM"]
    if os.environ.get("CAMPWATCH_EMAIL_TO"):
        email["to_address"] = os.environ["CAMPWATCH_EMAIL_TO"]
    if os.environ.get("CAMPWATCH_SMTP_SERVER"):
        email["smtp_server"] = os.environ["CAMPWATCH_SMTP_SERVER"]

    ntfy = n.setdefault("ntfy", {})
    if os.environ.get("CAMPWATCH_NTFY_TOPIC"):
        ntfy["topic"] = os.environ["CAMPWATCH_NTFY_TOPIC"]

    sms = n.setdefault("sms", {})
    if os.environ.get("CAMPWATCH_SMS_GATEWAY"):
        sms["sms_gateway_address"] = os.environ["CAMPWATCH_SMS_GATEWAY"]

    return cfg


def sync_remote_config(local_config_path: str) -> None:
    """If remote_settings.json exists alongside the config, pull the latest
    config.yaml from GitHub before using it. This is what makes editing
    config.yaml from the mobile app (docs/index.html) actually reach a
    desktop running in continuous mode -- otherwise the desktop would only
    ever see whatever config.yaml it started with.

    remote_settings.json format:
        {"owner": "yourusername", "repo": "campwatch", "token": "github_pat_..." }
    The token is optional -- omit it for a public repo.
    Safe to call on every cycle: it's a single lightweight GitHub API call,
    and failures are logged and ignored (the local config keeps working).
    """
    settings_path = Path(local_config_path).parent / "remote_settings.json"
    if not settings_path.exists():
        return

    try:
        settings = json.loads(settings_path.read_text())
        owner, repo = settings["owner"], settings["repo"]
        token = settings.get("token")

        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"https://api.github.com/repos/{owner}/{repo}/contents/config.yaml"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        content_b64 = resp.json()["content"]
        remote_yaml = base64.b64decode(content_b64).decode("utf-8")

        current = Path(local_config_path).read_text() if Path(local_config_path).exists() else ""
        if remote_yaml != current:
            Path(local_config_path).write_text(remote_yaml)
            logger.info("Pulled updated config.yaml from GitHub (%s/%s)", owner, repo)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not sync config from GitHub, using local copy: %s", e)


def setup_logging(cfg: dict[str, Any]) -> None:
    log_file = cfg.get("log_file", "campwatch.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s\t%(levelname)s\t%(name)s\t%(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )


def now_local(cfg: dict[str, Any]) -> datetime:
    tz = ZoneInfo(cfg["schedule"]["timezone"])
    return datetime.now(tz)


def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def is_within_window(current: datetime, start_s: str, end_s: str) -> bool:
    sh, sm = _parse_hhmm(start_s)
    eh, em = _parse_hhmm(end_s)
    start = current.replace(hour=sh, minute=sm, second=0, microsecond=0)
    end = current.replace(hour=eh, minute=em, second=0, microsecond=0)
    return start <= current <= end


def in_active_hours(cfg: dict[str, Any], current: datetime) -> bool:
    sched = cfg["schedule"]
    if current.strftime("%A") in sched.get("skip_days", []):
        return False
    return any(
        is_within_window(current, w["start"], w["end"]) for w in sched["active_hours"]
    )


def seconds_until_next_active_window(cfg: dict[str, Any], current: datetime) -> float:
    sched = cfg["schedule"]
    candidates = []
    for day_offset in range(0, 8):
        day = current + timedelta(days=day_offset)
        if day.strftime("%A") in sched.get("skip_days", []):
            continue
        for w in sched["active_hours"]:
            sh, sm = _parse_hhmm(w["start"])
            start = day.replace(hour=sh, minute=sm, second=0, microsecond=0)
            if start > current:
                candidates.append(start)
    if not candidates:
        return 3600.0
    return (min(candidates) - current).total_seconds()


def in_peak_window(cfg: dict[str, Any], current: datetime) -> bool:
    peak = cfg["speed"].get("peak", {})
    if not peak.get("enabled"):
        return False
    return any(is_within_window(current, w["start"], w["end"]) for w in peak["windows"])


def interval_minutes_for(cfg: dict[str, Any], watch_type: str, peak: bool) -> int:
    if watch_type == "coverage":
        return cfg["speed"]["coverage_interval_minutes"]
    if peak:
        return cfg["speed"]["peak"]["interval_minutes"]
    return cfg["speed"]["targeted_interval_minutes"]


# --------------------------------------------------------------------------
# State persistence: dedup notifications + per-watch last-checked timestamps
# --------------------------------------------------------------------------

def load_state(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"notified": {}, "watch_meta": {}}
    try:
        state = json.loads(p.read_text())
    except json.JSONDecodeError:
        logger.warning("State file %s was corrupt, starting fresh", path)
        return {"notified": {}, "watch_meta": {}}
    state.setdefault("notified", {})
    state.setdefault("watch_meta", {})
    return state


def save_state(path: str, state: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(state, indent=2))


def already_notified(state: dict[str, Any], facility_id: str, unit_id: int, date: str) -> bool:
    return date in state["notified"].get(facility_id, {}).get(str(unit_id), [])


def mark_notified(state: dict[str, Any], facility_id: str, unit_id: int, date: str) -> None:
    state["notified"].setdefault(facility_id, {}).setdefault(str(unit_id), [])
    if date not in state["notified"][facility_id][str(unit_id)]:
        state["notified"][facility_id][str(unit_id)].append(date)


def is_due(state: dict[str, Any], watch_key: str, interval_minutes: int, current: datetime) -> bool:
    last = state["watch_meta"].get(watch_key, {}).get("last_checked")
    if not last:
        return True
    last_dt = datetime.fromisoformat(last)
    return current >= last_dt + timedelta(minutes=interval_minutes)

def mark_checked(state: dict[str, Any], watch_key: str, current: datetime) -> None:
    state["watch_meta"][watch_key] = {"last_checked": current.isoformat()}


# --------------------------------------------------------------------------
# Watch execution
# --------------------------------------------------------------------------

@dataclass
class WatchResult:
    watch_name: str
    facility_name: str
    facility_id: str
    new_hits: list[tuple[rc_client.Unit, str]] = field(default_factory=list)


def run_watch(watch: dict[str, Any], state: dict[str, Any]) -> WatchResult | None:
    facility_id = str(watch["facility_id"])
    start = datetime.strptime(watch["start_date"], "%Y-%m-%d")
    end = datetime.strptime(watch["end_date"], "%Y-%m-%d")
    keywords = watch.get("keywords", [])
    exclude_ada = watch.get("exclude_ada", False)
    unit_id_filter = set(watch.get("unit_ids") or [])

    try:
        facility_name, units = rc_client.polite_get_availability(facility_id, start, end)
    except rc_client.ReserveCaliforniaError as e:
        logger.error("Watch '%s' failed: %s", watch["name"], e)
        return None

    result = WatchResult(watch["name"], facility_name, facility_id)
    for unit in units:
        if exclude_ada and unit.is_ada:
            continue
        if not unit.allow_web_booking:
            continue
        if unit_id_filter and unit.unit_id not in unit_id_filter:
            continue
        if not unit.matches_keywords(keywords):
            continue
        for date in unit.available_dates:
            if already_notified(state, facility_id, unit.unit_id, date):
                continue
            result.new_hits.append((unit, date))
    return result


def compose_message(results: list[WatchResult]) -> tuple[str, str]:
    total = sum(len(r.new_hits) for r in results)
    title = f"campwatch: {total} new opening{'s' if total != 1 else ''}"
    lines = []
    for r in results:
        if not r.new_hits:
            continue
        lines.append(f"\n{r.watch_name} -- {r.facility_name}")
        for unit, date in r.new_hits:
            lines.append(f"  {date}  site {unit.name} (unit {unit.unit_id})")
        lines.append(f"  Book: {rc_client.booking_link(r.facility_id)}")
    return title, "\n".join(lines).strip()


# --------------------------------------------------------------------------
# One scan cycle -- shared by `run` (loop) and `run-once` (scheduled)
# --------------------------------------------------------------------------

def execute_cycle(cfg: dict[str, Any], state: dict[str, Any]) -> list[WatchResult]:
    current = now_local(cfg)
    if not in_active_hours(cfg, current):
        logger.info("Outside active hours -- no watches checked this cycle.")
        return []

    peak = in_peak_window(cfg, current)
    min_gap = cfg["speed"].get("min_request_gap_seconds", 1.0)
    results: list[WatchResult] = []

    for watch_type, watches in (("coverage", cfg.get("coverage", [])),
                                 ("targeted", cfg.get("targeted", []))):
        interval = interval_minutes_for(cfg, watch_type, peak)
        for watch in watches:
            key = f"{watch_type}:{watch['name']}"
            if not is_due(state, key, interval, current):
                continue
            r = run_watch(watch, state)
            mark_checked(state, key, current)
            if r:
                for unit, date in r.new_hits:
                    mark_notified(state, r.facility_id, unit.unit_id, date)
                results.append(r)
            time.sleep(min_gap)

    return results


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def run_once(config_path: str) -> None:
    """Single pass: check any watches that are due, notify, save state, exit.
    Safe to invoke from any external scheduler (GitHub Actions, cron, Task
    Scheduler) on whatever cadence you like -- each watch honors its own
    interval independently via the persisted state file."""
    cfg = load_config(config_path)
    setup_logging(cfg)
    state = load_state(cfg["state_file"])

    results = execute_cycle(cfg, state)
    hits = [r for r in results if r.new_hits]

    if hits:
        title, body = compose_message(hits)
        logger.info("New availability found:\n%s", body)
        notifier.notify_all(cfg, title, body)
    else:
        logger.info("No new availability this cycle.")

    save_state(cfg["state_file"], state)


def run(config_path: str) -> None:
    """Continuous mode for an always-on machine (your desktop, a VPS, or a Pi)."""
    sync_remote_config(config_path)
    cfg = load_config(config_path)
    setup_logging(cfg)
    state = load_state(cfg["state_file"])
    logger.info(
        "campwatch starting (continuous mode): %d coverage watch(es), %d targeted watch(es)",
        len(cfg.get("coverage", [])), len(cfg.get("targeted", [])),
    )

    last_sync = now_local(cfg)

    while True:
        current = now_local(cfg)

        # Re-pull config.yaml from GitHub periodically, so edits made from
        # the mobile app reach this running process without a restart.
        if (current - last_sync).total_seconds() >= 300:  # every 5 minutes
            sync_remote_config(config_path)
            cfg = load_config(config_path)
            last_sync = current

        if not in_active_hours(cfg, current):
            sleep_s = seconds_until_next_active_window(cfg, current)
            logger.info("Outside active hours -- sleeping %.0f min", sleep_s / 60)
            time.sleep(min(sleep_s, 300))  # capped so we still re-sync config regularly
            continue

        results = execute_cycle(cfg, state)
        hits = [r for r in results if r.new_hits]
        if hits:
            title, body = compose_message(hits)
            logger.info("New availability found:\n%s", body)
            notifier.notify_all(cfg, title, body)
        save_state(cfg["state_file"], state)

        time.sleep(30)  # short tick; execute_cycle's is_due() gates real work per watch


def cmd_lookup(query: str) -> None:
    parks = rc_client.find_park(query)
    for park in parks[:5]:
        print(f"\nPark: {park['name']}  (place_id: {park['place_id']})")
        try:
            facilities = rc_client.find_facilities(park["place_id"])
        except rc_client.ReserveCaliforniaError as e:
            print(f"  (could not list facilities: {e})")
            continue
        for f in facilities:
            print(f"  facility_id: {f['facility_id']:>8}   {f['name']}")


def cmd_test_notify(config_path: str) -> None:
    cfg = load_config(config_path)
    setup_logging(cfg)
    notifier.notify_all(
        cfg,
        "campwatch: test notification",
        "If you're reading this, your notification channels are configured correctly.",
    )
    print("Test notification sent (check logs above for any channel errors).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Personal ReserveCalifornia cancellation scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_lookup = sub.add_parser("lookup", help="Find place_id and facility_id for a park by name")
    p_lookup.add_argument("query", help='Park name, e.g. "Pfeiffer Big Sur"')

    p_run = sub.add_parser("run", help="Continuous mode (always-on machine)")
    p_run.add_argument("--config", default="config.yaml")

    p_once = sub.add_parser("run-once", help="Single pass then exit (GitHub Actions / cron)")
    p_once.add_argument("--config", default="config.yaml")

    p_test = sub.add_parser("test-notify", help="Send a test notification through all enabled channels")
    p_test.add_argument("--config", default="config.yaml")

    args = parser.parse_args()
    if args.command == "lookup":
        cmd_lookup(args.query)
    elif args.command == "run":
        run(args.config)
    elif args.command == "run-once":
        run_once(args.config)
    elif args.command == "test-notify":
        cmd_test_notify(args.config)


if __name__ == "__main__":
    main()
