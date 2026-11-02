"""Presenter-paced state machine (UI-independent so it can be unit-tested).

NARRATING slide i  ->  (audio ends, cue 'please move to the next slide' is spoken)  ->  WAITING
WAITING + next  -> NARRATING i+1      WAITING + prev -> NARRATING i-1
any + repeat    -> NARRATING i        any + goto n   -> NARRATING n
last slide + next -> DONE
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PacedSession:
    total: int
    index: int = 0
    state: str = "IDLE"            # IDLE | NARRATING | WAITING | DONE
    log: List[str] = field(default_factory=list)

    def start(self, index: int = 0):
        self.index = max(0, min(index, self.total - 1)); self.state = "NARRATING"
        self.log.append(f"narrate {self.index + 1}")

    def narration_finished(self):
        if self.state == "NARRATING":
            self.state = "WAITING" if self.index < self.total - 1 else "DONE"
            self.log.append("cue+wait" if self.state == "WAITING" else "done")

    def command(self, cmd: Optional[str], arg: Optional[int] = None) -> bool:
        """Apply a command. Returns True if a new narration should start."""
        if cmd is None:
            return False
        if cmd == "next":
            if self.index >= self.total - 1:
                self.state = "DONE"; self.log.append("done"); return False
            self.index += 1
        elif cmd == "prev":
            self.index = max(0, self.index - 1)
        elif cmd == "goto" and arg:
            self.index = (self.total - 1) if arg == -1 else max(0, min(arg - 1, self.total - 1))
        elif cmd == "repeat":
            pass
        elif cmd == "stop":
            self.state = "IDLE"; self.log.append("stop"); return False
        else:
            return False
        self.state = "NARRATING"; self.log.append(f"narrate {self.index + 1}")
        return True
