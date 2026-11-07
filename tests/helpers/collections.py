"""Synthetic documents and one fake for the expensive text-runner boundary."""

import json


def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "Studies").mkdir(parents=True)
    (root / "Главная.md").write_text(
        "# Главная\n\nPerformance results: [[Studies/Experiment#Result]].\n"
    )
    (root / "Studies/Experiment.md").write_text(
        "---\naliases: [Latency study]\ntags:\n  - performance\n---\n# Experiment\n\n## Result\nMeasured latency was 7 ms. This was a single-machine test.\n"
    )
    (root / "unrelated.md").write_text("# Garden\nThe red rose is blooming.\n")
    return root


def navigation_context(prompt):
    """Inspect model-visible messages without replacing SDK behavior."""
    payload = json.loads(prompt.split("AGENT:\n", 1)[1])
    parts = [part for message in payload["history"] for part in message["parts"]]
    context = next(
        json.loads(part["content"])
        for part in parts
        if part["part_kind"] == "user-prompt" and part["content"].startswith("{")
    )
    context["memory"] = ""
    context["observations"] = [
        part["content"]
        for part in parts
        if part["part_kind"] == "tool-return"
        and part["tool_name"] == "retrieve"
        and part["outcome"] == "success"
    ]
    calls = [part for part in parts if part["part_kind"] == "tool-call"]
    if calls:
        args = calls[-1]["args"]
        context["memory"] = args.get("step", args)["memory"]
    context["retry"] = any(
        part["part_kind"] == "retry-prompt" or part.get("outcome") in ("failed", "retried")
        for part in parts
    )
    return context


class Navigator:
    def __init__(self, plan=None):
        self.calls, self.providers, self.navigation_prompts = [], [], []
        self.fail_answer = False
        self.plan = plan or self.step

    @staticmethod
    def step(ctx):
        root, phase = ctx["roots"][0]["id"], ctx["memory"]
        if phase == "":
            action = {"operation": "read", "collection_id": root, "path": "Главная.md"}
            memory = "index read"
        elif phase == "index read":
            action = {"operation": "links", "collection_id": root, "path": "Главная.md"}
            memory = "links found"
        elif phase == "links found":
            link = ctx["observations"][-1][0]["result"]["outgoing"][0]
            action = {
                "operation": "read",
                "collection_id": root,
                "path": link["paths"][0],
                "section": link["anchor"],
            }
            memory = "evidence read"
        else:
            action, memory = {"operation": "finish"}, phase
        return {"memory": memory, "actions": [action]}

    def __call__(self, prompt, schema, provider, model=None, **kwargs):
        self.calls.append(schema["title"])
        self.providers.append((provider, model))
        if schema["title"] == "NavigationStep":
            self.navigation_prompts.append(prompt)
            return self.plan(navigation_context(prompt))
        if self.fail_answer:
            raise RuntimeError("controlled writer failure")
        evidence = json.JSONDecoder().raw_decode(prompt.split("EVIDENCE:\n", 1)[1])[0]
        result = next(u for u in evidence if "Measured latency" in u["text"])
        return {
            "answer": "Latency was 7 ms in a single-machine test.",
            "evidence_status": "supported",
            "citations": [result["id"]],
            "quotes": [
                {
                    "citation": result["id"],
                    "text": "Measured latency was 7 ms. This was a single-machine test.",
                }
            ],
        }
