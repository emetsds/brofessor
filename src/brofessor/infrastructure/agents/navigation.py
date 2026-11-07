"""Pydantic AI navigation through brofessor's existing bounded text runners.

The app owns document operations and durable evidence. The SDK owns the agent
loop, tool argument validation, retries, and bounded message history.
"""

import asyncio
import hashlib
import os
import time

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.capabilities import ProcessHistory
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.usage import RequestUsage, UsageLimits

from brofessor import prompts
from brofessor.contracts.jobs import StageId
from brofessor.features.sources import navigation as source_navigation
from brofessor.features.sources import reading
from brofessor.prompts import ids as prompt_ids


class NavigationModel(Model):
    """Turn a typed navigation decision into one SDK tool call.

    Volatile SDK timestamps and run IDs do not identify an inference request.
    Stable tool-call IDs let the app replay a settled read without executing it
    again when the process dies between the tool and the next model request.
    """

    def __init__(self, generate, name):
        super().__init__()
        self.generate, self.name = generate, name

    @property
    def model_name(self):
        return self.name

    @property
    def system(self):
        return "brofessor-runner"

    async def request(self, messages, model_settings, model_request_parameters):
        _, parameters = self.prepare_request(model_settings, model_request_parameters)
        history = ModelMessagesTypeAdapter.dump_python(messages, mode="json")
        history = [
            {
                "kind": message["kind"],
                "parts": [
                    {
                        key: value
                        for key, value in part.items()
                        if key
                        in ("part_kind", "content", "tool_name", "args", "tool_call_id", "outcome")
                    }
                    for part in message["parts"]
                ],
            }
            for message in history
        ]
        payload = {
            "instructions": [p.content for p in parameters.instruction_parts or []],
            "history": history,
        }
        prompt = prompts.render(prompt_ids.NAVIGATION_STEP, agent=reading.encoded(payload))
        if len(prompt) > source_navigation.MAX_CONTEXT:
            raise ValueError("Agent history exceeds the navigation context budget")

        step = await asyncio.to_thread(
            self.generate, prompt, source_navigation.NavigationStep, citation_scope=set()
        )
        identity = hashlib.sha256(prompt.encode()).hexdigest()[:24]
        tool = (
            parameters.output_tools[0].name
            if step["actions"][0]["operation"] == "finish"
            else "retrieve"
        )
        return ModelResponse(
            parts=[ToolCallPart(tool, step if tool != "retrieve" else {"step": step}, identity)],
            model_name=self.model_name,
            usage=RequestUsage(unmeasured_requests=1),
        )


def run(session, generate, *, timeout=600):
    """Drive the shared read-only document operations with the real Agent loop."""
    state = session.state
    os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
    deadline = time.monotonic() + timeout
    if "harness_input" not in state:
        state["harness_input"] = session.context()
        session.save()

    def request(*args, **kwargs):
        session.check()
        session.progress(
            {
                "stage": StageId.SOURCE_NAVIGATION,
                "completed": len(state["steps"]),
                "total": source_navigation.MAX_STEPS,
                "selected_documents": len(state["documents"]),
                "read_fragments": len(state["units"]),
            }
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Navigation harness deadline exceeded")
        return generate(*args, **kwargs, timeout=remaining)

    def recent_history(messages):
        responses = [index for index, m in enumerate(messages) if isinstance(m, ModelResponse)]
        if len(responses) > 2:
            # Keep complete call/return pairs and the original task. Each call
            # carries the agent's short navigation memory, never primary evidence.
            return [messages[0], *messages[responses[-2] :]]
        return messages

    agent = Agent(
        NavigationModel(request, session.job["params"]["provider"]),
        output_type=source_navigation.NavigationStep,
        retries=2,
        capabilities=[ProcessHistory(recent_history)],
        instructions=(prompts.render(prompt_ids.NAVIGATION_AGENT)),
    )

    @agent.tool(description=prompts.render(prompt_ids.NAVIGATION_RETRIEVE))
    def retrieve(ctx: RunContext, step: source_navigation.NavigationStep) -> object:
        return session.apply(step.model_dump(), operation_id=ctx.tool_call_id)

    @agent.output_validator
    def finish(ctx: RunContext, step: source_navigation.NavigationStep):
        result = session.apply(step.model_dump(), operation_id=ctx.tool_call_id)
        if state["status"] != "complete":
            raise ModelRetry(reading.encoded(result))
        return step

    asyncio.run(
        agent.run(
            reading.encoded(state["harness_input"]),
            usage_limits=UsageLimits(request_limit=source_navigation.MAX_STEPS),
            timeout=timeout,
            infer_name=False,
        )
    )
    return state
