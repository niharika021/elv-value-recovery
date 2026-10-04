"""Ask the ELV agents a question; print the answer, the tools used, and the grounding check.

Run:  python -m app.elv_agent.ask "Why is V05's starter flagged?" ["follow-up" ...]
Questions after the first continue the same session.
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

from google.adk.runners import InMemoryRunner
from google.genai import types

from app.elv_agent.agent import root_agent
from app.elv_agent.grounding import ungrounded

APP, USER = "elv", "rvsf-team"


@dataclass
class Turn:
    question: str
    answer: str = ""
    calls: list[tuple[str, str, dict]] = field(default_factory=list)   # (agent, tool, args)
    results: list = field(default_factory=list)

    @property
    def tools(self) -> list[str]:
        return [t for _, t, _ in self.calls if t != "transfer_to_agent"]

    @property
    def agents(self) -> list[str]:
        return list(dict.fromkeys(a for a, _, _ in self.calls))

    @property
    def ungrounded(self) -> list[float]:
        return ungrounded(self.answer, self.results, self.question)


class Session:
    def __init__(self, agent=root_agent):
        self.runner = InMemoryRunner(agent=agent, app_name=APP)
        self.id = None

    async def ask(self, question: str) -> Turn:
        if self.id is None:
            s = await self.runner.session_service.create_session(app_name=APP, user_id=USER)
            self.id = s.id
        turn, final = Turn(question), []
        msg = types.Content(role="user", parts=[types.Part(text=question)])
        async for ev in self.runner.run_async(user_id=USER, session_id=self.id, new_message=msg):
            for p in (ev.content.parts if ev.content and ev.content.parts else []):
                if p.function_call:
                    turn.calls.append((ev.author, p.function_call.name, dict(p.function_call.args or {})))
                elif p.function_response:
                    turn.results.append(p.function_response.response)
                elif p.text and not p.thought and ev.author != "user" and ev.is_final_response():
                    final.append(p.text)
        turn.answer = "\n".join(final).strip()
        return turn


async def main(questions: list[str]) -> None:
    s = Session()
    for q in questions:
        t = await s.ask(q)
        print(f"\nQ: {q}\n\n{t.answer}\n")
        print(f"  agents: {' -> '.join(t.agents) or 'elv_coordinator'}   tools: {', '.join(t.tools) or 'none'}")
        print(f"  grounding: {'every number traced to a tool result' if not t.ungrounded else f'NOT FOUND in tool results: {t.ungrounded}'}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('Usage: python -m app.elv_agent.ask "question" ["follow-up" ...]')
    asyncio.run(main(sys.argv[1:]))
