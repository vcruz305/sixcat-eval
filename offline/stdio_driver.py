"""Drive sixcat's official --transport stdio protocol.

Modes:
  capture  - spawn sixcat with stdio transport, auto-answer every request with a
             dummy completion, and record the full request stream (throwaway run).
  run      - spawn sixcat again with fresh out/log paths and answer each request
             from the answers sheet, matched by prompt hash. Only the unscored
             policy probe may be answered from the built-in fallback.

Both modes accept overrides so new runs (different model id, fresh answer
sheets, fresh receipt paths) do not have to overwrite earlier artifacts:

  python stdio_driver.py capture --model glm-5.3 --prompts-out stdio_prompts_glm53.json
  python stdio_driver.py run --model glm-5.3 --answers answers_glm53.json \
      --out ../results/stdio-glm53.json --log ../results/stdio-glm53.jsonl
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROBE_SNIPPET = "What is 17 multiplied by 23?"


def sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def spawn(mode: str, out_path: Path, log_path: Path, model: str = "glm-5.3-flash"):
    cmd = [
        sys.executable, "-m", "sixcat",
        "--transport", "stdio",
        "--model", model,
        "--policy", "vendor",
        "--policy-family", "glm-5.x",
        "--limit", "20",
        "--out", str(out_path),
        "--log", str(log_path),
    ]
    proc = subprocess.Popen(
        cmd, cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8",
    )
    return proc, cmd


def serve(proc, answer_for):
    """Read request lines, dispatch to answer_for(req), write answer lines."""
    import threading

    stderr_chunks = []

    def drain_stderr():
        try:
            stderr_chunks.append(proc.stderr.read())
        except Exception:
            pass

    # sixcat prints per-item progress to stderr; drain it concurrently or the
    # OS pipe buffer fills and the child deadlocks while we read stdout.
    t = threading.Thread(target=drain_stderr, daemon=True)
    t.start()
    requests = []
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        requests.append(req)
        ans = answer_for(req)
        ans["id"] = req["id"]
        proc.stdin.write(json.dumps(ans, ensure_ascii=False) + "\n")
        proc.stdin.flush()
    proc.stdin.close()
    t.join(timeout=10)
    rc = proc.wait(timeout=60)
    return requests, rc, "".join(stderr_chunks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["capture", "run"])
    ap.add_argument("--model", default="glm-5.3-flash")
    ap.add_argument("--prompts-out", default="stdio_prompts.json",
                    help="capture: scored-request sheet to write (relative to offline/)")
    ap.add_argument("--answers", default="answers.json",
                    help="run: blind answer sheet to feed (relative to offline/)")
    ap.add_argument("--out", default=None,
                    help="run: result JSON path (relative to repo root); default results/stdio-glm53flash.json")
    ap.add_argument("--log", default=None,
                    help="run: journal JSONL path (relative to repo root); default alongside --out")
    args = ap.parse_args()

    if args.mode == "capture":
        with tempfile.TemporaryDirectory() as td:
            proc, cmd = spawn("capture", Path(td) / "out.json", Path(td) / "log.jsonl", args.model)
            requests, rc, stderr = serve(proc, lambda req: {
                "text": "A", "finish": "stop",
                "usage": {"completion_tokens": 1, "prompt_tokens": 10},
            })
        print(stderr[-1500:])
        print("exit:", rc, "requests:", len(requests))
        if rc != 0:
            sys.exit(1)
        scored = [r for r in requests if PROBE_SNIPPET not in r["prompt"]]
        (HERE / args.prompts_out).write_text(
            json.dumps(scored, indent=1, ensure_ascii=False), encoding="utf-8")
        print("recorded", len(scored), "scored requests (probe excluded) ->", args.prompts_out)
    else:
        answers = json.loads((HERE / args.answers).read_text(encoding="utf-8"))
        lookup = {}
        for a in answers:
            lookup[sha(a["prompt"])] = a
        results_dir = ROOT / "results"
        results_dir.mkdir(exist_ok=True)
        out_path = Path(args.out) if args.out else results_dir / "stdio-glm53flash.json"
        out_path = out_path if out_path.is_absolute() else ROOT / out_path
        log_path = Path(args.log) if args.log else out_path.with_suffix(".jsonl")
        log_path = log_path if log_path.is_absolute() else ROOT / log_path
        for p in (out_path, log_path):
            if p.exists():
                p.unlink()

        def answer_for(req):
            hit = lookup.get(sha(req["prompt"]))
            if hit is None:
                if PROBE_SNIPPET in req["prompt"]:
                    return {"text": "391", "finish": "stop"}
                raise SystemExit(f"unmatched stdio request (no blind answer): {req['prompt'][:120]!r}")
            out = {"text": hit.get("text", ""), "finish": "stop"}
            if hit.get("tool_calls"):
                out["tool_calls"] = [
                    {"function": {"name": c["name"], "arguments": json.dumps(c["arguments"])}}
                    for c in hit["tool_calls"]
                ]
            return out

        proc, cmd = spawn("run", out_path, log_path, args.model)
        requests, rc, stderr = serve(proc, answer_for)
        print(stderr)
        print("exit:", rc, "requests:", len(requests))
        sys.exit(rc)


if __name__ == "__main__":
    main()
