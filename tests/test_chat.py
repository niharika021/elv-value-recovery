"""Chat endpoint and Firestore store, offline: a stand-in session replaces Gemini, a fake client
replaces Firestore. These test our code paths, not the services themselves."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app.elv_agent.ask import Turn
from app.engines.audit import record_decision
from app.engines.decisions import Decision, FirestoreStore
from app.web import server
from app.web.chat import ChatLimit, ChatTimeout, RateLimiter, Sessions, answer


class FakeSession:
    def __init__(self):
        self.asked = []

    async def ask(self, q):
        self.asked.append(q)
        t = Turn(q, answer=f"V05 offer is INR 41,984 ({len(self.asked)})")
        t.calls = [("elv_coordinator", "vehicle_value", {"vehicle_id": "V05"})]
        t.results = [{"value": {"offer": 41984}}]
        return t


# ---- rate limit and sessions ----------------------------------------------------------------

def test_rate_limit_per_visitor_with_sliding_window():
    now = [0.0]
    lim = RateLimiter(per_hour=2, clock=lambda: now[0])
    lim.check("a"); lim.check("a")
    with pytest.raises(ChatLimit):
        lim.check("a")
    lim.check("b")                    # another visitor is unaffected
    now[0] = 3601
    lim.check("a")                    # window has moved on


def test_sessions_continue_by_id_and_cap_old_ones():
    s = Sessions(factory=FakeSession, cap=2)
    a, sa = s.get(None)
    assert s.get(a)[1] is sa
    s.get(None); s.get(None)
    assert s.get(a)[1] is not sa      # dropped as oldest; a fresh session takes its place


def test_answer_reports_tools_and_grounding():
    s = Sessions(factory=FakeSession)
    d = asyncio.run(answer(s, RateLimiter(10), "x", "  What is V05 worth? ", None))
    assert d["answer"].startswith("V05 offer is INR 41,984") and d["tools"] == ["vehicle_value"]
    assert d["ungrounded"] == [1]     # the "(1)" counter is not in any tool result: reported, not hidden
    again = asyncio.run(answer(s, RateLimiter(10), "x", "and again?", d["session_id"]))
    assert again["session_id"] == d["session_id"] and again["answer"].endswith("(2)")


class HangingSession:
    async def ask(self, q):
        await asyncio.sleep(3600)


def test_a_hung_agent_run_times_out_and_starts_a_new_conversation():
    s = Sessions(factory=HangingSession)
    sid, _ = s.get(None)
    with pytest.raises(ChatTimeout):
        asyncio.run(answer(s, RateLimiter(10), "x", "q", sid, timeout_s=0.05))
    assert s.get(sid)[0] != sid


def test_gemini_requests_have_a_timeout():
    from app.elv_agent.agent import CONFIG, inspection_agent, root_agent
    assert CONFIG.http_options.timeout and root_agent.generate_content_config is CONFIG
    assert inspection_agent.generate_content_config is CONFIG


@pytest.mark.parametrize("q", ["", "   ", "x" * 501])
def test_empty_or_long_questions_are_refused(q):
    with pytest.raises(ValueError):
        asyncio.run(answer(Sessions(factory=FakeSession), RateLimiter(10), "x", q, None))


# ---- endpoint ----------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "SESSIONS", Sessions(factory=FakeSession))
    monkeypatch.setattr(server, "LIMITER", RateLimiter(per_hour=2))
    return TestClient(server.app)


def test_chat_endpoint(client):
    r = client.post("/api/chat", json={"question": "What is V05 worth?"})
    assert r.status_code == 200 and r.json()["session_id"]


def test_chat_limit_is_429_and_spoofed_forwarding_does_not_dodge_it(client):
    for spoof in ("1.1.1.1", "2.2.2.2"):
        assert client.post("/api/chat", json={"question": "q"}, headers={"x-forwarded-for": f"{spoof}, 9.9.9.9"}).status_code == 200
    r = client.post("/api/chat", json={"question": "q"}, headers={"x-forwarded-for": "3.3.3.3, 9.9.9.9"})
    assert r.status_code == 429 and "limit" in r.json()["detail"]


def test_empty_question_is_400(client):
    assert client.post("/api/chat", json={"question": " "}).status_code == 400


# ---- Firestore store against a fake client ------------------------------------------------------

class FakeDoc:
    def __init__(self, data): self._d = data
    def to_dict(self): return dict(self._d)


class FakeQuery:
    def __init__(self, docs, field=None, desc=False, n=None):
        self.docs, self.field, self.desc, self.n = docs, field, desc, n
    def order_by(self, field, direction="ASCENDING"): return FakeQuery(self.docs, field, direction == "DESCENDING", self.n)
    def limit(self, n): return FakeQuery(self.docs, self.field, self.desc, n)
    def stream(self):
        rows = sorted(self.docs.values(), key=lambda d: d[self.field], reverse=self.desc) if self.field else list(self.docs.values())
        return [FakeDoc(d) for d in rows[: self.n]]


class FakeCollection(FakeQuery):
    def __init__(self): super().__init__({})
    def document(self, doc_id):
        col = self
        class Ref:
            def create(self, data):
                if doc_id in col.docs:
                    raise RuntimeError("409 already exists")   # Firestore refuses to overwrite on create()
                col.docs[doc_id] = data
        return Ref()


class FakeClient:
    def __init__(self): self.cols = {}
    def collection(self, name): return self.cols.setdefault(name, FakeCollection())


def test_firestore_store_keeps_order_and_feeds_the_engines():
    store = FirestoreStore("decisions", client=FakeClient())
    assert store.all() == [] and store.version() == "0"
    a = record_decision(store, Decision(engineer="E", kind="part_review", vehicle_id="V08", action="accept",
                                        target="ALT-08", reason="spin test quiet"))
    b = record_decision(store, Decision(engineer="E", kind="sign_off", vehicle_id="V09", action="sign"))
    assert [d.id for d in store.all()] == [a.id, b.id] and store.version() != "0"
    assert store.all()[0].context["engine_verdict"] == "reuse"


def test_firestore_store_never_overwrites():
    store = FirestoreStore("decisions", client=FakeClient())
    d = Decision(engineer="E", kind="sign_off", vehicle_id="V09", action="sign")
    store.append(d)
    with pytest.raises(RuntimeError):
        store.append(d)
