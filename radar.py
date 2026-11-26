#!/usr/bin/env python3
"""free-vps-radar: 免费 VPS / 免费额度补货雷达.

Watch a list of pages / JSON endpoints and notify (Telegram) only when a
target transitions from out-of-stock to in-stock.

Standard library only. No pip dependencies.
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
FETCH_TIMEOUT = 20  # seconds

IN = "in"
OUT = "out"
UNKNOWN = "unknown"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch(url, timeout=FETCH_TIMEOUT):
    """Fetch a URL and return the decoded body as text. Raises on error."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def get_dotted(data, path):
    """Read a dotted path like 'data.stock.count' from nested dicts/lists."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return cur


def classify(target, body):
    """Return IN or OUT for a fetched body according to the target's mode.

    Raises ValueError on a malformed target / unparsable body.
    """
    mode = target.get("mode")

    if mode == "keyword_absent":
        keyword = target["keyword"]
        return OUT if keyword in body else IN

    if mode == "keyword_present":
        keyword = target["keyword"]
        return IN if keyword in body else OUT

    if mode == "json_field":
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"response is not valid JSON: {exc}") from exc
        value = get_dotted(data, target["field"])
        expect = target.get("expect")
        op = target.get("op", "equals")
        if op == "equals":
            return IN if value == expect else OUT
        if op == ">=":
            try:
                return IN if value is not None and float(value) >= float(expect) else OUT
            except (TypeError, ValueError) as exc:
                raise ValueError(f"json_field >= comparison failed: {exc}") from exc
        raise ValueError(f"unknown json_field op: {op!r}")

    raise ValueError(f"unknown mode: {mode!r}")


def check_target(target, fetch_fn=fetch):
    """Fetch and classify one target. Returns IN/OUT, or None on fetch error
    (errors never change state)."""
    body = fetch_fn(target["url"])
    return classify(target, body)


def send_telegram(text):
    """Send a Telegram message using TG_BOT_TOKEN / TG_CHAT_ID env vars.

    Returns True if sent, False if env vars are missing or sending failed.
    Never raises.
    """
    token = os.environ.get("TG_BOT_TOKEN")
    chat_id = os.environ.get("TG_CHAT_ID")
    if not token or not chat_id:
        log("TG_BOT_TOKEN / TG_CHAT_ID not set; alert printed only, not sent.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=payload)
    try:
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            resp.read()
        return True
    except Exception as exc:  # noqa: BLE001 - notification must never crash the run
        log(f"Telegram send failed: {exc}")
        return False


def notify(target, dry_run=False, send_fn=send_telegram):
    text = (
        f"🎉 补货提醒：{target['name']} 现在有货了！\n"
        f"{target['url']}"
    )
    if dry_run:
        log(f"[dry-run] WOULD notify: {text}")
        return
    log(f"ALERT: {text}")
    send_fn(text)


def load_state(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError) as exc:
            log(f"State file unreadable ({exc}); starting fresh.")
    return {}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def run_once(config, state, *, dry_run=False, notify_first=False,
             fetch_fn=fetch, send_fn=send_telegram):
    """One check pass over all targets. Mutates `state` in place (unless
    dry_run). Returns a list of target names that notified (or would)."""
    notified = []
    for target in config.get("targets", []):
        name = target.get("name", target.get("url", "?"))
        try:
            result = check_target(target, fetch_fn=fetch_fn)
        except urllib.error.URLError as exc:
            log(f"[{name}] fetch error: {exc}; keeping previous state.")
            continue
        except Exception as exc:  # noqa: BLE001 - one bad target must not kill the run
            log(f"[{name}] check failed: {exc}; keeping previous state.")
            continue

        prev = state.get(name, UNKNOWN)
        log(f"[{name}] state: {prev} -> {result}")
        if result == IN and prev != IN:
            if prev == UNKNOWN and not notify_first:
                log(f"[{name}] in-stock on first sight; not notifying "
                    f"(pass --notify-first to change this).")
            else:
                notify(target, dry_run=dry_run, send_fn=send_fn)
                notified.append(name)
        if not dry_run:
            state[name] = result
    return notified


def load_config(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="免费 VPS / 免费额度补货雷达 (free VPS restock radar)")
    parser.add_argument("--config", default="config.json",
                        help="path to config JSON (default: config.json)")
    parser.add_argument("--state", default="state.json",
                        help="path to state JSON (default: state.json)")
    parser.add_argument("--once", action="store_true",
                        help="run a single check pass and exit")
    parser.add_argument("--interval", type=int, default=300,
                        help="seconds between passes in loop mode (default: 300)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what WOULD notify; no state write, no send")
    parser.add_argument("--notify-first", action="store_true",
                        help="also notify when a target is in-stock on first run")
    parser.add_argument("--test-notify", action="store_true",
                        help="send one test Telegram message and exit")
    args = parser.parse_args(argv)

    if args.test_notify:
        ok = send_telegram("✅ free-vps-radar 测试消息：通知通道正常。")
        log("Test message sent." if ok else
            "Test message NOT sent (see log above).")
        return 0

    try:
        config = load_config(args.config)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"Cannot load config {args.config}: {exc}")
        return 1

    state = load_state(args.state)

    if args.once or args.dry_run:
        run_once(config, state, dry_run=args.dry_run,
                 notify_first=args.notify_first)
        if not args.dry_run:
            save_state(args.state, state)
        return 0

    log(f"Loop mode: checking every ~{args.interval}s. Ctrl+C to stop.")
    try:
        while True:
            run_once(config, state, notify_first=args.notify_first)
            save_state(args.state, state)
            jitter = random.uniform(0, min(30, args.interval * 0.1))
            time.sleep(args.interval + jitter)
    except KeyboardInterrupt:
        log("Stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
