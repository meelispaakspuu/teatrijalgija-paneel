"""Kontrollimise sageduse teisendamine GitHub Actionsi cron-ridadeks (UTC).

Workflow-failis on ajakava kahe markeri vahel; paneel asendab ainult selle ploki.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Tallinn")
START = "    # AJAKAVA-ALGUS (muudab juhtpaneel, ära muuda käsitsi markereid)"
END = "    # AJAKAVA-LÕPP"
INTERVALS = [15, 20, 30, 60, 120, 180]
FREE_MINUTES = 2000  # privaatse repo Free plaan, min/kuus


def _utc_offset_hours(now: datetime | None = None) -> int:
    now = now or datetime.now(TZ)
    return int(now.astimezone(TZ).utcoffset().total_seconds() // 3600)


def day_hours_local(start_h: int, end_h: int) -> list[int]:
    """Kohalikud tunnid [start, end); end=24 tähendab südaööni. Üle südaöö: nt 7..1."""
    if start_h == end_h:
        return list(range(24))
    if start_h < end_h:
        return list(range(start_h, end_h))
    return list(range(start_h, 24)) + list(range(0, end_h))


def build_crons(interval_min: int, start_h: int, end_h: int, night_checks: bool,
                now: datetime | None = None) -> list[str]:
    """Tagastab cron-avaldised (UTC). Minut 7 jne, et vältida täistunni koormust."""
    off = _utc_offset_hours(now)
    hours = day_hours_local(start_h, end_h)
    if interval_min >= 60:
        step = interval_min // 60
        hours = hours[::step]
        minutes = "7"
    else:
        minutes = ",".join(str(7 + i * interval_min) for i in range(60 // interval_min))
    utc = sorted({(h - off) % 24 for h in hours})
    crons = [f"{minutes} {','.join(map(str, utc))} * * *"]
    if night_checks:
        night_local = [h for h in (3, 6) if h not in hours]
        if night_local:
            crons.append(f"7 {','.join(str((h - off) % 24) for h in night_local)} * * *")
    return crons


def runs_per_day(crons: list[str]) -> int:
    n = 0
    for c in crons:
        mins, hrs = c.split()[:2]
        n += len(mins.split(",")) * len(hrs.split(","))
    return n


def monthly_minutes(crons: list[str], billed_per_run: int = 1) -> int:
    return runs_per_day(crons) * 31 * billed_per_run


def replace_block(workflow_yaml: str, crons: list[str]) -> str:
    if START not in workflow_yaml or END not in workflow_yaml:
        raise ValueError("Workflow-failis pole AJAKAVA markereid")
    a = workflow_yaml.index(START) + len(START)
    b = workflow_yaml.index(END)
    body = "".join(f'\n    - cron: "{c}"' for c in crons) + "\n"
    return workflow_yaml[:a] + body + workflow_yaml[b:]


def current_crons(workflow_yaml: str) -> list[str]:
    a = workflow_yaml.find(START)
    b = workflow_yaml.find(END)
    if a < 0 or b < 0:
        return re.findall(r'cron:\s*"([^"]+)"', workflow_yaml)
    return re.findall(r'cron:\s*"([^"]+)"', workflow_yaml[a:b])
