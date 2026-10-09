"""A stand-in for the `claude` CLI that speaks its stream-json format.

The prompt arrives on stdin. Behaviour depends on the prompt:
  "sleep N"  says it is working, then sleeps N seconds (to test queueing and interrupts)
  "fail"     ends with an error result
  image messages (--input-format stream-json) become "text [media types]"
  otherwise  appends the prompt to AGENT.md, like a real agent editing a file
"""

import json
import os
import signal
import sys
import time

args = sys.argv[1:]
session = None
for flag in ("--session-id", "--resume"):
    if flag in args:
        session = args[args.index(flag) + 1]
resumed = "--resume" in args
prompt = sys.stdin.read().strip()
if "--input-format" in args:
    # Image messages arrive as one JSON line; echo the images' types after the text.
    content = json.loads(prompt)["message"]["content"]
    text = "".join(b["text"] for b in content if b["type"] == "text")
    kinds = ",".join(b["source"]["media_type"] for b in content if b["type"] == "image")
    prompt = f"{text} [{kinds}]"


def emit(obj: dict) -> None:
    print(json.dumps({**obj, "session_id": session}), flush=True)


signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
print("warning: this is a fake agent", file=sys.stderr, flush=True)
emit({"type": "system", "subtype": "init", "model": "fake-model", "cwd": os.getcwd()})
emit(
    {
        "type": "assistant",
        "parent_tool_use_id": None,
        "message": {
            "content": [
                {"type": "thinking", "thinking": "Planning", "signature": "x"},
                {"type": "text", "text": f"{'Resumed' if resumed else 'Started'}: {prompt}"},
            ]
        },
    }
)

if prompt.startswith("env "):
    name = prompt.split()[1]
    emit(
        {
            "type": "assistant",
            "parent_tool_use_id": None,
            "message": {"content": [{"type": "text", "text": f"{name}={os.environ.get(name)}"}]},
        }
    )
elif prompt.startswith("sleep"):
    time.sleep(float(prompt.split()[1]))
elif prompt == "fail":
    emit(
        {
            "type": "result",
            "subtype": "error_during_execution",
            "is_error": True,
            "errors": ["Something broke"],
            "total_cost_usd": 0.001,
            "usage": {},
        }
    )
    sys.exit(1)
else:
    with open("AGENT.md", "a") as f:
        f.write(prompt + "\n")
    emit(
        {
            "type": "assistant",
            "parent_tool_use_id": None,
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Write",
                        "input": {"file_path": "AGENT.md", "content": prompt},
                    }
                ]
            },
        }
    )
    emit(
        {
            "type": "user",
            "parent_tool_use_id": None,
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": [{"type": "text", "text": "ok"}],
                    }
                ]
            },
        }
    )

emit(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "Done",
        "total_cost_usd": 0.01,
        "num_turns": 1,
        "duration_ms": 5,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50},
    }
)
