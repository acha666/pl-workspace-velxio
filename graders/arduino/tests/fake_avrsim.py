"""A stand-in for avrsim that replays a script, for Session tests without the toolchain.

Usage: fake_avrsim.py SCRIPT LOG [FIRMWARE]

SCRIPT lists the records to report, one per line, as ``P CYCLE PIN STATE`` or
``S CYCLE BYTE``, plus optionally ``DONE CYCLE REASON``, after which the program
has stopped for good; ``DIE MESSAGE``, which makes the next run exit with
status 3 and MESSAGE on stderr; and ``GARBAGE LINE``, which makes the next run
reply with LINE in place of a record. Records at cycle 0 are reported at start, as
avrsim reports the initial pin states. Every command received is appended to LOG.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    script, log = Path(sys.argv[1]), Path(sys.argv[2])
    records: list[tuple[int, str]] = []
    done: tuple[int, str] | None = None
    die: str | None = None
    garbage: str | None = None
    for line in script.read_text().splitlines():
        kind, _, rest = line.strip().partition(" ")
        if kind in ("P", "S"):
            at, _, detail = rest.partition(" ")
            records.append((int(at), f"{kind} {at} {detail}"))
        elif kind == "DONE":
            at, _, reason = rest.partition(" ")
            done = (int(at), reason)
        elif kind == "DIE":
            die = rest
        elif kind == "GARBAGE":
            garbage = rest
    records.sort(key=lambda record: record[0])
    for cycle, record in records:
        if cycle == 0:
            print(record, flush=True)
    now = 0
    stopped: str | None = None
    with log.open("a") as logged:
        for line in sys.stdin:
            command = line.rstrip("\n")
            logged.write(command + "\n")
            logged.flush()
            words = command.split()
            if words[0] != "run":
                continue
            if die is not None:
                print(die, file=sys.stderr, flush=True)
                return 3
            if garbage is not None:
                print(garbage, flush=True)
                garbage = None
                continue
            if stopped is not None:
                print(f"T {now} {stopped}", flush=True)
                continue
            target = int(words[1])
            watch = (words[3], int(words[4])) if len(words) > 4 else None
            end = min(target, done[0]) if done else target
            reason = "reached"
            for cycle, record in records:
                if cycle <= now or cycle > end:
                    continue
                print(record, flush=True)
                fields = record.split()
                if watch and fields[0] == watch[0] and watch[1] in (-1, int(fields[2])):
                    now, reason = cycle, "watched"
                    break
            else:
                if done and done[0] <= target:
                    now, stopped = done
                    reason = stopped
                else:
                    now = target
            print(f"T {now} {reason}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
