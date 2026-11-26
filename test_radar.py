#!/usr/bin/env python3
"""Tests for radar.py. The fetch function is stubbed; no network is used."""

import json
import unittest

import radar


def make_config(target):
    return {"targets": [target]}


class FakeFetch:
    """Returns a fixed body, or raises a fixed exception."""

    def __init__(self, body="", exc=None):
        self.body = body
        self.exc = exc

    def __call__(self, url):
        if self.exc is not None:
            raise self.exc
        return self.body


class Recorder:
    """send_fn stub that records messages."""

    def __init__(self):
        self.sent = []

    def __call__(self, text):
        self.sent.append(text)
        return True


KW_ABSENT = {"name": "t-absent", "url": "http://x", "mode": "keyword_absent",
             "keyword": "SOLD OUT"}
KW_PRESENT = {"name": "t-present", "url": "http://x", "mode": "keyword_present",
              "keyword": "Claim now"}
JSON_FIELD = {"name": "t-json", "url": "http://x", "mode": "json_field",
              "field": "data.available", "op": ">=", "expect": 1}
JSON_EQ = {"name": "t-json-eq", "url": "http://x", "mode": "json_field",
           "field": "status", "op": "equals", "expect": "in_stock"}


class TestClassify(unittest.TestCase):
    def test_keyword_absent(self):
        self.assertEqual(radar.classify(KW_ABSENT, "Sorry, SOLD OUT"), radar.OUT)
        self.assertEqual(radar.classify(KW_ABSENT, "Free tier available"), radar.IN)

    def test_keyword_present(self):
        self.assertEqual(radar.classify(KW_PRESENT, "Click Claim now"), radar.IN)
        self.assertEqual(radar.classify(KW_PRESENT, "Coming soon"), radar.OUT)

    def test_json_field_ge(self):
        body = json.dumps({"data": {"available": 3}})
        self.assertEqual(radar.classify(JSON_FIELD, body), radar.IN)
        body = json.dumps({"data": {"available": 0}})
        self.assertEqual(radar.classify(JSON_FIELD, body), radar.OUT)

    def test_json_field_equals(self):
        self.assertEqual(radar.classify(JSON_EQ, '{"status": "in_stock"}'), radar.IN)
        self.assertEqual(radar.classify(JSON_EQ, '{"status": "gone"}'), radar.OUT)


class TestTransitions(unittest.TestCase):
    def test_out_to_in_notifies_exactly_once(self):
        config = make_config(KW_ABSENT)
        state = {}
        sender = Recorder()
        # First run: out of stock.
        radar.run_once(config, state, fetch_fn=FakeFetch("SOLD OUT"),
                       send_fn=sender)
        self.assertEqual(sender.sent, [])
        self.assertEqual(state["t-absent"], radar.OUT)
        # Second run: restocked -> notify once.
        notified = radar.run_once(config, state,
                                  fetch_fn=FakeFetch("available"),
                                  send_fn=sender)
        self.assertEqual(notified, ["t-absent"])
        self.assertEqual(len(sender.sent), 1)
        # Third run: still in stock -> no re-notify.
        notified = radar.run_once(config, state,
                                  fetch_fn=FakeFetch("available"),
                                  send_fn=sender)
        self.assertEqual(notified, [])
        self.assertEqual(len(sender.sent), 1)

    def test_in_to_in_no_notify(self):
        config = make_config(KW_PRESENT)
        state = {"t-present": radar.IN}
        sender = Recorder()
        radar.run_once(config, state, fetch_fn=FakeFetch("Claim now"),
                       send_fn=sender)
        self.assertEqual(sender.sent, [])

    def test_first_run_in_stock_silent_by_default(self):
        config = make_config(KW_ABSENT)
        state = {}
        sender = Recorder()
        radar.run_once(config, state, fetch_fn=FakeFetch("available"),
                       send_fn=sender)
        self.assertEqual(sender.sent, [])
        self.assertEqual(state["t-absent"], radar.IN)

    def test_first_run_in_stock_notifies_with_flag(self):
        config = make_config(KW_ABSENT)
        state = {}
        sender = Recorder()
        radar.run_once(config, state, fetch_fn=FakeFetch("available"),
                       notify_first=True, send_fn=sender)
        self.assertEqual(len(sender.sent), 1)

    def test_fetch_error_keeps_state_and_no_notify(self):
        config = make_config(KW_ABSENT)
        state = {"t-absent": radar.OUT}
        sender = Recorder()
        err = radar.urllib.error.URLError("boom")
        radar.run_once(config, state, fetch_fn=FakeFetch(exc=err),
                       send_fn=sender)
        self.assertEqual(state["t-absent"], radar.OUT)
        self.assertEqual(sender.sent, [])

    def test_dry_run_does_not_write_state_or_send(self):
        config = make_config(KW_ABSENT)
        state = {"t-absent": radar.OUT}
        sender = Recorder()
        notified = radar.run_once(config, state,
                                  fetch_fn=FakeFetch("available"),
                                  dry_run=True, send_fn=sender)
        self.assertEqual(notified, ["t-absent"])
        self.assertEqual(sender.sent, [])
        self.assertEqual(state["t-absent"], radar.OUT)  # unchanged

    def test_one_bad_target_does_not_kill_run(self):
        bad = {"name": "bad", "url": "http://x", "mode": "nope"}
        config = {"targets": [bad, KW_PRESENT]}
        state = {}
        sender = Recorder()
        radar.run_once(config, state, fetch_fn=FakeFetch("Claim now"),
                       send_fn=sender)
        self.assertEqual(state["t-present"], radar.IN)


if __name__ == "__main__":
    unittest.main()
