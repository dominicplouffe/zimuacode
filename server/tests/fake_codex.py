"""A stand-in for the `codex` CLI: `exec --json` (with `resume`) and the `cloud` commands.

exec reads the prompt from stdin ("-") and appends it to CODEX.md, like a real edit.
"""

import json
import os
import sys
import uuid

args = sys.argv[1:]


def emit(obj: dict) -> None:
    print(json.dumps(obj), flush=True)


if args[:1] == ["cloud"]:
    sub = args[1]
    if sub == "exec":
        print("Task created")
        print("https://chatgpt.com/codex/tasks/task_e_fake123")
    elif sub == "status":
        print("READY")
    elif sub == "diff":
        sys.stdout.write(
            "diff --git a/CLOUD.md b/CLOUD.md\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/CLOUD.md\n"
            "@@ -0,0 +1 @@\n"
            "+made in the cloud\n"
        )
    sys.exit(0)

assert args[0] == "exec" and "--json" in args and args[-1] == "-", args
thread = args[args.index("resume") + 1] if "resume" in args else str(uuid.uuid4())
prompt = sys.stdin.read().strip().splitlines()[-1]

emit({"type": "thread.started", "thread_id": thread})
emit({"type": "turn.started"})
emit({"type": "item.completed", "item": {"id": "i0", "type": "reasoning", "text": "Thinking"}})
emit(
    {
        "type": "item.updated",
        "item": {
            "id": "i1",
            "type": "todo_list",
            "items": [{"text": "edit file", "completed": False}],
        },
    }
)
emit(
    {
        "type": "item.started",
        "item": {
            "id": "i2",
            "type": "command_execution",
            "command": "ls",
            "aggregated_output": "",
            "exit_code": None,
            "status": "in_progress",
        },
    }
)
emit(
    {
        "type": "item.completed",
        "item": {
            "id": "i2",
            "type": "command_execution",
            "command": "ls",
            "aggregated_output": "README.md\n",
            "exit_code": 0,
            "status": "completed",
        },
    }
)
with open("CODEX.md", "a") as f:
    f.write(prompt + "\n")
emit(
    {
        "type": "item.completed",
        "item": {
            "id": "i3",
            "type": "file_change",
            "changes": [{"path": os.path.join(os.getcwd(), "CODEX.md"), "kind": "add"}],
            "status": "completed",
        },
    }
)
verb = "Resumed" if "resume" in args else "Started"
emit(
    {
        "type": "item.completed",
        "item": {"id": "i4", "type": "agent_message", "text": f"{verb}: {prompt}"},
    }
)
emit(
    {
        "type": "turn.completed",
        "usage": {
            "input_tokens": 1000,
            "cached_input_tokens": 800,
            "output_tokens": 50,
            "reasoning_output_tokens": 10,
        },
    }
)
