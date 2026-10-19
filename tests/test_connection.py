"""Connection modes: when a net set to "needed" links, and DMR timeslots."""

import asyncio
from datetime import datetime

import pytest

from hamcast import schedule
from hamcast.config import StreamConfig, validate_stream
from hamcast.dmr.client import station_config
from hamcast.stream import DmrStream, VoiceStream, dmr_plus_options


def ts(*args):
    return datetime(*args).timestamp()  # local time, like the rules


def net(**kw):
    s = StreamConfig(id="n", name="N", type="ysf", host="h", port=1, mount="", **kw)
    validate_stream(s, None)
    return s


# ========== RULES KEPT IN HAMCAST ==========

UFB = {"days": ["sun"], "time": "19:30", "minutes": 90}
MOTA = {"days": ["thu"], "time": "19:00", "minutes": 60, "weeks": [3]}


def test_weekly_rule_with_lead_and_length():
    rules = [schedule.validate_rule(UFB, "n")]
    # Sunday 2026-10-25
    assert not schedule.rules_active(rules, 10, ts(2026, 10, 25, 19, 19))
    assert schedule.rules_active(rules, 10, ts(2026, 10, 25, 19, 20))
    assert schedule.rules_active(rules, 10, ts(2026, 10, 25, 20, 59))
    assert not schedule.rules_active(rules, 10, ts(2026, 10, 25, 21, 0))
    assert schedule.rules_next(rules, ts(2026, 10, 25, 21, 0)) == ts(2026, 11, 1, 19, 30)


def test_nth_weekday_rule():
    rules = [schedule.validate_rule(MOTA, "n")]
    assert schedule.rules_next(rules, ts(2026, 10, 1)) == ts(2026, 10, 15, 19, 0)  # 3rd Thursday
    assert not schedule.rules_active(rules, 0, ts(2026, 10, 22, 19, 30))  # 4th Thursday


def test_rule_running_past_midnight():
    rules = [schedule.validate_rule({"days": ["sat"], "time": "23:30", "minutes": 60}, "n")]
    assert schedule.rules_active(rules, 0, ts(2026, 10, 25, 0, 15))  # Sunday 00:15


def test_bad_rules_are_refused():
    for bad in ({"days": [], "time": "19:00"}, {"days": ["sun"], "time": "7pm"},
                {"days": ["sun"], "time": "19:00", "weeks": [6]}):
        with pytest.raises(ValueError):
            schedule.validate_rule(bad, "n")


# ========== ECTLOGGER ==========

def calendar(*occurrences):
    c = schedule.EctloggerCalendar("https://example.org")
    c.occurrences = [{"schedule": 9, "cancelled": False, **o} for o in occurrences]
    return c


def test_ectlogger_follows_the_net():
    start = 1_000_000.0
    c = calendar({"start": start, "status": "scheduled"})
    assert not c.active(9, 10, start - 601)
    assert c.active(9, 10, start - 600)
    assert c.active(9, 10, start + schedule.WAIT_FOR_START)  # waiting for it to open
    assert not c.active(9, 10, start + schedule.WAIT_FOR_START + 1)
    assert calendar({"start": start, "status": "active"}).active(9, 10, start + 4 * 3600)  # runs long
    assert not calendar({"start": start, "status": "closed"}).active(9, 10, start + 60)
    assert not calendar({"start": start, "status": "scheduled", "cancelled": True}).active(9, 10, start)
    assert not c.active(3, 10, start)  # another schedule


def test_api_base():
    assert schedule._api_base("https://app.ectlogger.us/") == "https://app.ectlogger.us/api"
    assert schedule._api_base("https://app.ectlogger.us/api") == "https://app.ectlogger.us/api"


# ========== WANTED ==========

def test_wanted():
    now = 1_000_000.0
    assert schedule.wanted(net(), 0, 0.0, None, now)  # always
    on_demand = net(connection="needed")
    assert not schedule.wanted(on_demand, 0, 0.0, None, now)
    assert schedule.wanted(on_demand, 1, now, None, now)
    assert schedule.wanted(on_demand, 0, now - 299, None, now)  # lingering after the last listener
    assert not schedule.wanted(on_demand, 0, now - 301, None, now)
    followed = net(connection="needed", on_listen=False, ectlogger_schedule=9)
    assert schedule.wanted(followed, 0, 0.0, calendar({"start": now, "status": "lobby"}), now)
    assert not schedule.wanted(followed, 5, now, None, now)  # listeners don't count for it


def test_needed_without_any_trigger_is_refused():
    with pytest.raises(ValueError, match="never links"):
        net(connection="needed", on_listen=False)


# ========== THE LINK GATE ==========

def test_link_runs_only_while_wanted():
    class Fake(VoiceStream):
        runs = 0
        linked = False

        def _is_linked(self):
            return self.linked

        async def _run_source(self, stop):
            Fake.runs += 1
            self.linked = True
            await stop.wait()
            self.linked = False

    async def go():
        s = Fake("n")
        s.set_wanted(False)
        stop = asyncio.Event()
        task = asyncio.create_task(s._run_source_when_wanted(stop))
        await asyncio.sleep(0.05)
        seen = [s.linked]
        s.set_wanted(True)
        await asyncio.sleep(0.05)
        seen.append(s.linked)
        s.set_wanted(False)
        await asyncio.sleep(0.05)
        seen.append(s.linked)
        stop.set()
        await task
        return seen

    assert asyncio.run(go()) == [False, True, False] and Fake.runs == 1


# ========== DMR TIMESLOTS ==========

def test_dmr_talkgroups_go_on_their_timeslot():
    statewide, office = DmrStream("dirigo", 3123, slot=1), DmrStream("officehours", 8801)
    opts = dmr_plus_options([statewide, office])
    assert opts == "StartRef=4000;RelinkTime=60;UserLink=0;TS1_1=3123;TS2_1=8801;"
    assert dmr_plus_options([office]) == "StartRef=4000;RelinkTime=60;UserLink=0;TS2_1=8801;"


def test_station_config_slots():
    # callsign 8, rx 9, tx 9, power 2, colour 2, lat 8, lon 9, height 3, location 20, description 19
    assert station_config("N0CALL", "hamcast", "u")[89:90] == b"4"
    assert station_config("N0CALL", "hamcast", "u", duplex=True)[89:90] == b"3"
    assert len(station_config("N0CALL", "hamcast", "u", duplex=True)) == 294
