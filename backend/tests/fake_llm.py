"""A scripted OpenAI-compatible model for tests. It answers from the KEYS line in the system prompt and
records every request, so tests can see exactly what each agent was given."""

import json
import re

import httpx

KEYS_LINE = re.compile(r"KEYS: (.*)")


class FakeLLM:
    def __init__(self, reviewer_verdict: str = "pass", reviewer_findings: list[str] | None = None) -> None:
        self.reviewer_verdict = reviewer_verdict
        self.reviewer_findings = reviewer_findings or []
        self.requests: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        user = body["messages"][1]["content"]
        self.requests.append({"system": system, "user": user})
        keys = [k.strip() for k in KEYS_LINE.search(system).group(1).split(",")]
        if keys == ["verdict", "findings"]:
            answer = {"verdict": self.reviewer_verdict, "findings": self.reviewer_findings}
        else:
            answer = {key: f"{key} written from the input" for key in keys}
        payload = {
            "model": body["model"],
            "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }
        return httpx.Response(200, json=payload)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def lead_requests(self) -> list[dict]:
        return [r for r in self.requests if "KEYS: verdict, findings" not in r["system"]]

    def review_requests(self) -> list[dict]:
        return [r for r in self.requests if "KEYS: verdict, findings" in r["system"]]
