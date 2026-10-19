"""When a net set to connection "needed" should be linked by schedule.

Two sources, either or both per net:

- Rules kept in hamcast: {"days": ["sun"], "time": "19:30", "minutes": 90,
  "weeks": [3]}, in local time (TZ). "weeks" picks which of the month's
  weekdays count (3 = the third Sunday); empty or missing = every week.
- An ECTLogger schedule, read from that site's public calendar
  (GET /api/templates/calendar, see ECTLogger's routers/templates_calendar.py).
  Each occurrence carries its schedule id and the net's status, so the
  link follows the actual net: from lead_minutes before its start, through
  its lobby and while it is active, until it is closed.
"""

import asyncio
import json
import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger(__name__)

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# ECTLogger: how long past its start a net that hasn't opened yet is waited for.
WAIT_FOR_START = 60 * 60
CALENDAR_REFRESH = 5 * 60
_ENDED = {"closed", "archived", "cancelled"}
_LIVE = {"lobby", "active"}


# ========== RULES KEPT IN HAMCAST ==========

def validate_rule(rule: dict, stream_id: str) -> dict:
    days = [str(d).lower()[:3] for d in rule.get("days") or []]
    if not days or any(d not in DAYS for d in days):
        raise ValueError(f"stream {stream_id}: each schedule needs days (mon..sun)")
    if not _TIME.match(str(rule.get("time", ""))):
        raise ValueError(f"stream {stream_id}: schedule time must be HH:MM")
    minutes = int(rule.get("minutes", 60))
    if not 1 <= minutes <= 1440:
        raise ValueError(f"stream {stream_id}: a scheduled net lasts 1 to 1440 minutes")
    weeks = sorted({int(w) for w in rule.get("weeks") or []})
    if any(not 1 <= w <= 5 for w in weeks):
        raise ValueError(f"stream {stream_id}: weeks of the month are 1 to 5")
    return {"days": sorted(set(days), key=DAYS.index), "time": rule["time"], "minutes": minutes, "weeks": weeks}


def _starts_on(rule: dict, day: date) -> float | None:
    """The rule's start on this local date, as a timestamp, if it has one."""
    if DAYS[day.weekday()] not in rule["days"]:
        return None
    if rule["weeks"] and (day.day - 1) // 7 + 1 not in rule["weeks"]:
        return None
    hour, minute = map(int, rule["time"].split(":"))
    return datetime(day.year, day.month, day.day, hour, minute).timestamp()  # local time


def rules_active(rules: list[dict], lead_minutes: int, now: float) -> bool:
    today = datetime.fromtimestamp(now).date()
    for rule in rules:
        for day in (today - timedelta(days=1), today):  # yesterday's may run past midnight
            start = _starts_on(rule, day)
            if start is not None and start - lead_minutes * 60 <= now < start + rule["minutes"] * 60:
                return True
    return False


def rules_next(rules: list[dict], now: float) -> float | None:
    """The next start of any rule after now."""
    today = datetime.fromtimestamp(now).date()
    starts = [s for rule in rules for n in range(0, 40)
              if (s := _starts_on(rule, today + timedelta(days=n))) is not None and s > now]
    return min(starts, default=None)


# ========== ECTLOGGER ==========

def _api_base(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/api") else url + "/api"


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "hamcast", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def _ts(iso: str) -> float:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


class EctloggerCalendar:
    """The site's upcoming and current nets, refreshed every few minutes.
    If a refresh fails the last good copy is kept."""

    def __init__(self, url: str) -> None:
        self.api = _api_base(url)
        self.occurrences: list[dict] = []
        self.error: str | None = None

    def refresh(self) -> None:
        """Blocking."""
        now = datetime.now(timezone.utc)
        query = urllib.parse.urlencode({"start": (now - timedelta(days=1)).isoformat(),
                                        "end": (now + timedelta(days=14)).isoformat()})
        try:
            data = _get_json(f"{self.api}/templates/calendar?{query}")
            self.occurrences = [
                {"schedule": o.get("template_id"), "start": _ts(o["start"]),
                 "status": (o.get("status") or "").lower(), "cancelled": bool(o.get("is_cancelled"))}
                for o in data]
            self.error = None
        except Exception as exc:
            self.error = str(exc)
            log.warning("cannot read the ECTLogger calendar at %s: %s", self.api, exc)

    def schedules(self) -> list[dict]:
        """[{id, name}] for the dashboard's picker. Blocking."""
        return [{"id": t["id"], "name": t["name"]} for t in _get_json(f"{self.api}/templates/")]

    def _of(self, schedule: int) -> list[dict]:
        return [o for o in self.occurrences if o["schedule"] == schedule and not o["cancelled"]]

    def active(self, schedule: int, lead_minutes: int, now: float) -> bool:
        for o in self._of(schedule):
            if o["status"] in _LIVE:
                return True
            if o["status"] not in _ENDED and o["start"] - lead_minutes * 60 <= now <= o["start"] + WAIT_FOR_START:
                return True
        return False

    def next_start(self, schedule: int, now: float) -> float | None:
        return min((o["start"] for o in self._of(schedule)
                    if o["start"] > now and o["status"] not in _ENDED), default=None)

    async def run(self, stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            await loop.run_in_executor(None, self.refresh)
            try:
                await asyncio.wait_for(stop.wait(), CALENDAR_REFRESH)
            except asyncio.TimeoutError:
                pass


def wanted(scfg, listeners: int, last_listener: float, calendar: EctloggerCalendar | None,
           now: float | None = None) -> bool:
    """Whether a net should be linked right now."""
    if scfg.connection == "always":
        return True
    now = time.time() if now is None else now
    if scfg.on_listen and (listeners > 0 or now - last_listener < scfg.linger_minutes * 60):
        return True
    if scfg.schedule and rules_active(scfg.schedule, scfg.lead_minutes, now):
        return True
    return bool(scfg.ectlogger_schedule and calendar
                and calendar.active(scfg.ectlogger_schedule, scfg.lead_minutes, now))


def next_link(scfg, calendar: EctloggerCalendar | None, now: float | None = None) -> float | None:
    """When the net's schedule next starts (for "Next: ..." on the page)."""
    now = time.time() if now is None else now
    starts = [rules_next(scfg.schedule, now) if scfg.schedule else None,
              calendar.next_start(scfg.ectlogger_schedule, now)
              if scfg.ectlogger_schedule and calendar else None]
    return min((s for s in starts if s), default=None)
