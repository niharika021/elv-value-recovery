"""Chat with the ELV agents from the web app: one ADK session per browser tab, rate-limited.

Each answer comes back with the agents and tools used and the grounding check, so the screen can
show whether every number traced to a tool result. Sessions live in this process's memory, so
on Cloud Run the service is deployed with --session-affinity: a visitor's follow-up questions
reach the instance holding their conversation. A restart starts fresh conversations (the
decision log is unaffected).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import OrderedDict, defaultdict, deque

MAX_QUESTION = 500
MAX_SESSIONS = 200
LIMIT_PER_HOUR = int(os.environ.get("CHAT_LIMIT_PER_HOUR", "30"))   # per visitor
CHAT_TIMEOUT_S = float(os.environ.get("CHAT_TIMEOUT_S", "120"))       # whole question, all agents


log = logging.getLogger("coreyield.chat")


class ChatTimeout(Exception):
    pass


class ChatUpstream(Exception):
    """The agent run failed (for example Gemini returned an error); the visitor should ask again."""


class ChatLimit(Exception):
    pass


class RateLimiter:
    """Sliding one-hour window per client key."""

    def __init__(self, per_hour: int = LIMIT_PER_HOUR, clock=time.monotonic):
        self.per_hour, self.clock, self.hits = per_hour, clock, defaultdict(deque)

    def check(self, key: str) -> None:
        now, q = self.clock(), self.hits[key]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= self.per_hour:
            wait = int(3600 - (now - q[0])) // 60 + 1
            raise ChatLimit(f"Question limit reached ({self.per_hour} an hour). Try again in about {wait} min.")
        q.append(now)


class Sessions:
    """Agent sessions by id, oldest dropped past MAX_SESSIONS."""

    def __init__(self, factory=None, cap: int = MAX_SESSIONS):
        self.factory, self.cap, self._s = factory, cap, OrderedDict()

    def drop(self, sid: str) -> None:
        self._s.pop(sid, None)

    def get(self, sid: str | None):
        if sid and sid in self._s:
            self._s.move_to_end(sid)
            return sid, self._s[sid]
        if self.factory is None:
            from app.elv_agent.ask import Session
            self.factory = Session
        sid = uuid.uuid4().hex
        self._s[sid] = self.factory()
        while len(self._s) > self.cap:
            self._s.popitem(last=False)
        return sid, self._s[sid]


async def answer(sessions: Sessions, limiter: RateLimiter, client: str, question: str, sid: str | None,
                 timeout_s: float = CHAT_TIMEOUT_S) -> dict:
    q = (question or "").strip()
    if not q:
        raise ValueError("Ask a question.")
    if len(q) > MAX_QUESTION:
        raise ValueError(f"Keep questions under {MAX_QUESTION} characters.")
    limiter.check(client)
    sid, s = sessions.get(sid)
    t0 = time.monotonic()
    try:
        turn = await asyncio.wait_for(s.ask(q), timeout_s)
    except asyncio.TimeoutError as e:
        sessions.drop(sid)   # a half-finished turn would confuse the next question
        raise ChatTimeout(f"The agents took longer than {timeout_s:g} s. Please ask again; "
                          "a new conversation has been started.") from e
    except Exception as e:  # noqa: BLE001 - any failed agent run must reach the visitor as a clear message
        sessions.drop(sid)
        log.exception("agent run failed")
        raise ChatUpstream("The agents could not finish this answer (the AI service returned an error). "
                           "Please ask again; a new conversation has been started.") from e
    return dict(session_id=sid, question=q, answer=turn.answer or "(no answer)", agents=turn.agents,
                tools=turn.tools, ungrounded=turn.ungrounded, seconds=round(time.monotonic() - t0, 1))
