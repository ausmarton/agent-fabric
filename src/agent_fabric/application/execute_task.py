"""
Execute task use case: recruit specialist, create run, run tool loop, return result.
Depends on ports only (ChatClient, RunRepository, SpecialistRegistry).
"""

from __future__ import annotations

from typing import Any, Dict, List

from agent_fabric.config import FabricConfig, ModelConfig, load_config
from agent_fabric.domain import RunId, RunResult, Task
from agent_fabric.application.ports import ChatClient, RunRepository, SpecialistRegistry
from agent_fabric.application.json_parsing import extract_json
from agent_fabric.application.recruit import recruit_specialist


async def execute_task(
    task: Task,
    *,
    chat_client: ChatClient,
    run_repository: RunRepository,
    specialist_registry: SpecialistRegistry,
    config: FabricConfig | None = None,
    resolved_model_cfg: ModelConfig | None = None,
    workspace_root: str = ".fabric",
    max_steps: int = 40,
) -> RunResult:
    """
    Execute a task: recruit specialist (if not set), create run, run tool loop, return result.
    """
    if config is None:
        config = load_config()
    specialist_id = task.specialist_id or recruit_specialist(task.prompt, config)
    if specialist_id not in config.specialists:
        raise ValueError(f"Unknown specialist: {specialist_id}")

    run_id, run_dir, workspace_path = run_repository.create_run()
    pack = specialist_registry.get_pack(specialist_id, workspace_path, task.network_allowed)
    model_cfg = resolved_model_cfg or config.models.get(task.model_key) or config.models["quality"]

    tool_names_str = ", ".join(pack.tool_names)
    system_content = pack.system_prompt + "\n\n" + pack.tool_loop_prompt(tool_names_str)
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": (
            f"Task:\n{task.prompt}\n\n"
            "Perform the task now. Use tools (e.g. write_file, shell, list_files, read_file) for each step—do not reply with only a plan. "
            "Output exactly one JSON object per turn: use action \"tool\" with tool_name and args to run a tool; when the task is done, use action \"final\" with summary and artifacts. No markdown, no extra text."
        )},
    ]

    payload: Dict[str, Any] = {}
    for step in range(max_steps):
        run_repository.append_event(run_id, "llm_request", {"messages_tail": messages[-3:]}, step=f"step_{step}")
        text = await chat_client.chat(
            messages=messages,
            model=model_cfg.model,
            temperature=model_cfg.temperature,
            top_p=model_cfg.top_p,
            max_tokens=model_cfg.max_tokens,
        )
        run_repository.append_event(run_id, "llm_response", {"text": text[:4000]}, step=f"step_{step}")

        ok, obj, err = extract_json(text)
        if not ok or not isinstance(obj, dict):
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"Your previous output was not valid JSON ({err}). Output ONLY a valid JSON object per the schema."})
            continue

        action = obj.get("action")
        if action == "final":
            payload = obj
            break

        if action != "tool":
            messages.append({"role": "user", "content": "Invalid action. Use action='tool' or action='final'."})
            continue

        tool_name = obj.get("tool_name")
        args = obj.get("args", {})
        if tool_name not in pack.tool_names:
            messages.append({"role": "user", "content": f"Unknown tool '{tool_name}'. Available: {pack.tool_names}"})
            continue

        run_repository.append_event(run_id, "tool_call", {"tool": tool_name, "args": args}, step=f"step_{step}")
        try:
            result = pack.execute_tool(tool_name, args)
        except Exception as e:
            result = {"error": str(e)}
        run_repository.append_event(run_id, "tool_result", {"tool": tool_name, "result": result}, step=f"step_{step}")

        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": f"Tool result for {tool_name}:\n{result}\n\nContinue. Remember quality gates: run tests/build; if failing, fix."})
    else:
        payload = {
            "action": "final",
            "summary": "Hit max_steps before completion.",
            "artifacts": [],
            "next_steps": ["Increase max_steps or refine task."],
            "notes": "See runlog for details.",
        }

    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        workspace_path=workspace_path,
        specialist_id=specialist_id,
        model_name=model_cfg.model,
        payload=payload,
    )
