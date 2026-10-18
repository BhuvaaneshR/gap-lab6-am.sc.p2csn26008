#!/usr/bin/env python3
"""
harness.py: Lab 6 marking script.

    python harness.py path/to/student_repo
    python harness.py --all path/to/all_submissions --out results/

Runs 16 checks worth 8.5 marks, plus three gates. No network. No reading
anyone's code.

It works on a temporary copy of the repo and overwrites the copy's client.py
and stub_client.py with its own, so a student who edited the stub gains
nothing. The student's own samples/*.json, observability.py, security.py,
doc_loader.py and tools.py are kept: the samples define their schema and the
rest are theirs to extend.

It rewrites corpus/ inside the temporary copy between checks, so the two
injection payloads are tested one at a time. Nothing it does touches the
student's own repository, logs or question store.

Shipped to students unchanged, under the name check.py. Without the
reference_files/ folder beside it, it prints "self-check mode" and takes
their supplied files as they are.

Requires the marker's Python to have: pydantic, python-dotenv, openai,
pypdf, python-pptx.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCE = HERE / "reference_files"     # holds client.py and stub_client.py
SELF_CHECK = not REFERENCE.exists()      # student copy: no reference dir shipped


def ref(name: str, repo: Path) -> Path:
    """The authoritative copy of a supplied file, or the repo's own in self-check."""
    return (repo / name) if SELF_CHECK else (REFERENCE / name)


TIMEOUT = 60           # one run of main.py, including any backoff sleeps
LOOP_TIMEOUT = 120     # stub:neverstop gets longer before it is called a hang

REQUIRED_FILES = [
    "main.py",
    "client.py",
    "stub_client.py",
    "observability.py",
    "doc_loader.py",
    "security.py",
    "tools.py",
    "check.py",
    "SPEC.md",
    "DECISIONS.md",
    "QUESTION.md",
    "ATTACK.md",
    "SECURITY.md",
    ".gitignore",
    "requirements.txt",
    ".env.example",
    "samples/valid_response.json",
    "samples/invalid_response.json",
    "samples/tool_trace.jsonl",
]

OUTCOMES = {"ok", "invalid_output", "refused", "error"}

# The marker stub:obedient appends when it obeys an instruction.
CANARY = "PWNED-7F3A"

# Planted outside the allow-list. If this ever comes back, a tool read it.
SENTINEL = "SENTINEL-OUTSIDE-ALLOWLIST-91B2"

CLEAN_DOCS = [
    "01_question_design_basics.md",
    "02_assessment_integrity.txt",
    "03_item_writing_guidelines.pdf",
    "05_bloom_taxonomy_notes.md",
]
OVERT_DOC = "06_exam_security_handbook.pdf"     # instruction block in the body
BURIED_DOC = "04_academic_integrity_deck.pptx"  # instruction in a speaker note

TOPIC = "Assessment design and item writing"

HARD_STEP_CEILING = 12   # a documented cap above this is not a cap


# --------------------------------------------------------------------------

@dataclass
class Check:
    group: str
    name: str
    marks: float
    passed: bool = False
    note: str = ""


@dataclass
class Gate:
    name: str
    passed: bool
    note: str = ""


@dataclass
class Result:
    repo: str
    checks: list[Check] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)

    @property
    def awarded(self) -> float:
        return round(sum(c.marks for c in self.checks if c.passed), 2)

    @property
    def total(self) -> float:
        return round(sum(c.marks for c in self.checks), 2)


@dataclass
class Run:
    mode: str
    last: str
    code: int
    err: str
    events: list[dict] = field(default_factory=list)     # parsed security_log.jsonl
    questions: list[dict] = field(default_factory=list)  # the store, after the run
    stdout: str = ""
    calls: int = 0
    timed_out: bool = False

    @property
    def event_names(self) -> set[str]:
        return {e.get("event", "") for e in self.events if isinstance(e, dict)}


def git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=20,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_jsonl(path: Path) -> tuple[list[dict], int]:
    """Parse a .jsonl file. Returns (records, number of unparseable lines)."""
    if not path.exists():
        return ([], 0)
    records, bad = [], 0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            bad += 1
    return (records, bad)


def read_store(repo: Path) -> list[dict]:
    """The question store, however the student wrapped it."""
    path = repo / "data" / "generated_questions.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("questions") if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def set_corpus(workdir: Path, names: list[str], pristine: Path) -> None:
    """Rewrite corpus/ in the temporary copy with a chosen subset."""
    corpus = workdir / "corpus"
    if corpus.exists():
        shutil.rmtree(corpus)
    corpus.mkdir(parents=True)
    for name in names:
        src = pristine / name
        if src.exists():
            shutil.copy2(src, corpus / name)


def run_app(workdir: Path, topic: str, mode: str, timeout: int = TIMEOUT) -> Run:
    """Run main.py once against one stub mode, with clean logs."""
    env = dict(os.environ)
    env["LLM_API_KEY"] = "not-needed"
    env["LLM_BASE_URL"] = "local://stub"
    env["LLM_MODEL"] = f"stub:{mode}"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("LLM_PROVIDER", None)
    env.pop("RUN_LOG_PATH", None)
    env.pop("GAP_RUN_ID", None)

    call_log = workdir / ".stub_calls.log"
    sec_log = workdir / "security_log.jsonl"
    call_log.unlink(missing_ok=True)
    sec_log.unlink(missing_ok=True)
    (workdir / "run_log.jsonl").unlink(missing_ok=True)

    timed_out = False
    try:
        proc = subprocess.run(
            [sys.executable, "main.py", topic],
            cwd=str(workdir), env=env, capture_output=True,
            text=True, timeout=timeout,
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, out, err, timed_out = -1, "", f"no output within {timeout}s", True

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    last = lines[-1] if lines else "<no output>"
    events, _ = read_jsonl(sec_log)
    calls = 0
    if call_log.exists():
        calls = len([ln for ln in call_log.read_text().splitlines() if ln.strip()])

    return Run(mode=mode, last=last, code=code, err=err.strip()[-300:],
               events=events, questions=read_store(workdir), stdout=out,
               calls=calls, timed_out=timed_out)


def probe_tools(workdir: Path) -> dict:
    """Import the student's tools module and dump what it exposes.

    Done in a subprocess so a broken tools.py cannot take the harness with it.
    """
    script = (
        'import json, sys\n'
        'sys.path.insert(0, ".")\n'
        'out = {"ok": False}\n'
        'try:\n'
        '    import tools\n'
        '    out["max_tool_steps"] = getattr(tools, "MAX_TOOL_STEPS", None)\n'
        '    out["schemas"] = json.loads(json.dumps(tools.get_tool_schemas(), default=str))\n'
        '    out["expected"] = {n: json.loads(json.dumps(m.model_json_schema(), default=str))\n'
        '                       for n, m in getattr(tools, "TOOL_ARGS", {}).items()}\n'
        '    out["ok"] = True\n'
        'except Exception as exc:\n'
        '    out["error"] = f"{type(exc).__name__}: {exc}"\n'
        'print("<<<PROBE>>>" + json.dumps(out))\n'
    )
    path = workdir / "_gap_probe.py"
    try:
        path.write_text(script, encoding="utf-8")
        proc = subprocess.run([sys.executable, "_gap_probe.py"], cwd=str(workdir),
                              capture_output=True, text=True, timeout=60)
        parts = (proc.stdout or "").split("<<<PROBE>>>")
        if len(parts) > 1:
            return json.loads(parts[-1].strip())
        return {"ok": False, "error": (proc.stderr or "no output")[-200:]}
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        path.unlink(missing_ok=True)


def strip_titles(node):
    """Pydantic puts 'title' on everything; students who strip it are not wrong."""
    if isinstance(node, dict):
        return {k: strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [strip_titles(v) for v in node]
    return node


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


# --------------------------------------------------------------------------

def check_repo(repo: Path) -> Result:
    res = Result(repo=repo.name)
    add = res.checks.append
    gate = res.gates.append

    # ---- Gates. Not marks. A failing one is a submission that cannot be
    #      marked, not a lost fraction. ------------------------------------
    student_client = repo / "client.py"
    same = student_client.exists() and (
        SELF_CHECK or sha256(student_client) == sha256(ref("client.py", repo))
    )
    gate(Gate("client.py unmodified", same,
              "" if same else "client.py differs from the supplied file"))

    tagged = "lab-6-submission" in git(repo, "tag", "-l", "lab-6-submission")
    gate(Gate("lab-6-submission tag present", tagged,
              "" if tagged else "run: git tag lab-6-submission && git push origin --tags"))

    history = git(repo, "log", "--all", "--name-only", "--pretty=format:")
    tracked = {ln.strip() for ln in history.splitlines()}
    gate(Gate(".env never committed, on any branch", ".env" not in tracked,
              "" if ".env" not in tracked else ".env appears in git history"))

    # ---- Prerequisites, reported so that a zero is explicable -------------
    missing = [f for f in REQUIRED_FILES if not (repo / f).exists()]
    gate(Gate("All required files present", not missing,
              "" if not missing else "missing: " + ", ".join(missing)))

    gitignore = (repo / ".gitignore").read_text(encoding="utf-8", errors="ignore") \
        if (repo / ".gitignore").exists() else ""
    ignored = all(x in gitignore for x in (".env", "run_log.jsonl", "security_log.jsonl"))
    leaked = sorted(f for f in ("run_log.jsonl", "security_log.jsonl") if f in tracked)
    gate(Gate("Logs ignored and never committed", ignored and not leaked,
              "" if ignored and not leaked else "; ".join(filter(None, [
                  "" if ignored else "one of .env, run_log.jsonl, security_log.jsonl "
                                     "is not in .gitignore",
                  ("committed at some point: " + ", ".join(leaked)) if leaked else "",
              ]))))

    if not (repo / "main.py").exists() or not (repo / "corpus").is_dir():
        for g, n, m in [("A", "Corpus ingestion works across formats", 1.0),
                        ("B", "Refuses an instruction found in a document", 1.5),
                        ("C", "Output validation and guardrails", 1.5),
                        ("D", "Tool schemas generated from Pydantic", 1.0),
                        ("E", "Tool security", 2.5),
                        ("F", "Duplicates and the trace", 1.0)]:
            add(Check(g, n, m, False, "no main.py or no corpus/ in the repository"))
        return res

    # ---- Behavioural checks, on a temporary copy --------------------------
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(repo, work, ignore=shutil.ignore_patterns(
            ".git", ".venv", "venv", "__pycache__", "*.pyc"))
        if not SELF_CHECK:
            shutil.copy2(REFERENCE / "stub_client.py", work / "stub_client.py")
            shutil.copy2(REFERENCE / "client.py", work / "client.py")
        (work / ".env").unlink(missing_ok=True)

        pristine = Path(tmp) / "corpus_pristine"
        shutil.copytree(repo / "corpus", pristine)

        baseline = {str(r.get("id", "")) for r in read_store(work)}

        # ---- Group A: ingestion (1.0) ------------------------------------
        set_corpus(work, CLEAN_DOCS + [BURIED_DOC, OVERT_DOC], pristine)
        r = run_app(work, TOPIC, "ok")

        try:
            index = json.loads(
                (work / "data" / "ingest_index.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            index = None
        rows = index if isinstance(index, list) else None

        a1 = bool(rows) and len(rows) >= 4 and all(isinstance(x, dict) for x in rows)
        add(Check("A", "data/ingest_index.json written, one entry per document",
                  0.4, a1,
                  "" if a1 else "missing, not a list, or fewer than 4 entries"))

        formats = {str(x.get("format", "")).lower() for x in rows} if a1 else set()
        sized = all(int(x.get("chars", 0) or 0) > 0 for x in rows) if a1 else False
        a2 = {"pdf", "pptx"} <= formats and sized
        add(Check("A", "Both hard formats ingested, every document non-empty",
                  0.3, a2,
                  "" if a2 else f"formats {sorted(formats) or 'none'}; "
                                f"all non-empty: {sized}"))

        sources = {str(x.get("source", "")) for x in rows} if a1 else set()
        fresh = [q for q in r.questions if str(q.get("id", "")) not in baseline]
        a3 = any(str(q.get("source", "")) and any(
            str(q.get("source", "")).replace("\\", "/").endswith(Path(s).name)
            for s in sources) for q in fresh)
        add(Check("A", "A stored question traceable to an ingested document",
                  0.3, a3,
                  "" if a3 else f"{len(fresh)} new question(s), "
                                "none citing an ingested source"))

        # ---- Group B: the instruction is refused (1.5) -------------------
        injection_events: set[str] = set()
        for label, doc, mark in (("overt block", OVERT_DOC, 0.75),
                                 ("speaker note", BURIED_DOC, 0.75)):
            set_corpus(work, CLEAN_DOCS + [doc], pristine)
            r = run_app(work, TOPIC, "obedient")
            injection_events |= r.event_names

            clean = CANARY not in r.stdout and CANARY not in json.dumps(r.questions)
            noticed = bool(r.event_names & {"guardrail_input", "instruction_ignored",
                                            "guardrail_output"})
            ok = clean and noticed
            add(Check("B", f"stub:obedient, {label} -> marker never stored or printed",
                      mark, ok,
                      "" if ok else "; ".join(filter(None, [
                          "" if clean else "the marker reached output or the store",
                          "" if noticed else "no guardrail_input, instruction_ignored "
                                             "or guardrail_output event logged",
                      ]))))

        # ---- Group C: output validation and guardrails (1.5) -------------
        set_corpus(work, CLEAN_DOCS, pristine)
        before = {str(q.get("id", "")) for q in read_store(work)}
        r = run_app(work, TOPIC, "badshape")

        c1 = r.last == "invalid_output" and r.code == 1
        add(Check("C", "stub:badshape -> invalid_output (exit 1)", 0.6, c1,
                  "" if c1 else f"got {r.last!r} exit {r.code}"
                  + (f"; stderr: {r.err.splitlines()[-1]}" if r.err else "")))

        after = {str(q.get("id", "")) for q in r.questions}
        c2 = after <= before
        add(Check("C", "Nothing stored from a reply that failed validation",
                  0.4, c2,
                  "" if c2 else f"{len(after - before)} question(s) stored anyway"))

        c3 = {"guardrail_input", "guardrail_output"} <= injection_events
        add(Check("C", "Both an input and an output guardrail actually ran",
                  0.5, c3,
                  "" if c3 else "events across the injection runs: "
                                f"{sorted(injection_events) or 'none'}"))

        # ---- Group D: schemas from Pydantic (1.0) ------------------------
        probe = probe_tools(work)
        if not probe.get("ok"):
            add(Check("D", "get_tool_schemas() returns both tools", 0.3, False,
                      f"could not import tools: {probe.get('error', 'unknown')}"))
            add(Check("D", "topic_lookup parameters match its Pydantic model",
                      0.35, False, "not reached"))
            add(Check("D", "question_lookup parameters match its Pydantic model",
                      0.35, False, "not reached"))
        else:
            by_name = {}
            for entry in probe.get("schemas") or []:
                if isinstance(entry, dict) and isinstance(entry.get("function"), dict):
                    by_name[entry["function"].get("name")] = entry["function"]
            expected = probe.get("expected") or {}

            wanted = {"topic_lookup", "question_lookup"}
            d0 = wanted <= set(by_name)
            add(Check("D", "get_tool_schemas() returns both tools", 0.3, d0,
                      "" if d0 else f"exposed: {sorted(by_name) or 'none'}"))

            for name in ("topic_lookup", "question_lookup"):
                want = strip_titles(expected.get(name, {}))
                got = strip_titles((by_name.get(name) or {}).get("parameters", {}))
                ok = bool(want) and got == want
                note = ""
                if not ok:
                    wp = set(want.get("properties") or {})
                    gp = set(got.get("properties") or {})
                    if wp and wp == gp:
                        note = ("field names match but the body differs from "
                                "model_json_schema(); that is what a hand-written "
                                "dict looks like")
                    else:
                        note = (f"missing {sorted(wp - gp) or 'none'}, "
                                f"extra {sorted(gp - wp) or 'none'}")
                add(Check("D", f"{name} parameters match its Pydantic model",
                          0.35, ok, note))

        # ---- Group E: tool security (2.5) -------------------------------
        set_corpus(work, CLEAN_DOCS, pristine)
        env_decoy = work / ".env"
        env_decoy.write_text(
            f"LLM_API_KEY={SENTINEL}\nLLM_BASE_URL=local://stub\nLLM_MODEL=stub:ok\n",
            encoding="utf-8")
        json_decoy = work / "topics_backup.json"
        json_decoy.write_text(json.dumps(
            {"topics": [{"id": "T99", "name": f"assessment {SENTINEL}"}]}),
            encoding="utf-8")
        try:
            r = run_app(work, TOPIC, "traversal")
        finally:
            env_decoy.unlink(missing_ok=True)
            json_decoy.unlink(missing_ok=True)

        # Containment, not refusal. A tool whose argument was never a path reads
        # nothing and logs nothing, and that is the right answer, so requiring a
        # refusal event here would penalise the correct design.
        #
        # What this observes is escape, not the open itself: a tool that opens
        # the file and then discards it passes. That shape is caught by a human
        # reading SECURITY.md, not by this script.
        haystack = r.stdout + r.err + json.dumps(r.questions) + json.dumps(r.events)
        trace_file = work / "samples" / "tool_trace.jsonl"
        if trace_file.exists():
            haystack += trace_file.read_text(encoding="utf-8", errors="ignore")
        e1 = SENTINEL not in haystack
        add(Check("E", "stub:traversal -> nothing outside data/ reaches the model",
                  0.7, e1,
                  "" if e1 else "a file above data/ was opened and its contents "
                                "escaped into the reply, the store or the trace"))

        # Gate 2: the third call omits the required argument, so it fails the
        # Pydantic model whatever constraints the student chose.
        e2 = "tool_arg_rejected" in r.event_names
        add(Check("E", "A call that fails the argument model is refused and logged",
                  0.5, e2,
                  "" if e2 else "no tool_arg_rejected event for the call with the "
                                "required argument missing; events "
                                f"{sorted(r.event_names) or 'none'}"))

        e3 = r.last in OUTCOMES and not r.timed_out
        add(Check("E", "The refused call is handled, not crashed into", 0.3, e3,
                  "" if e3 else f"ended {r.last!r} exit {r.code}"))

        r = run_app(work, TOPIC, "toolcall")
        e4 = "tool_result_rejected" in r.event_names
        add(Check("E", "stub:toolcall -> the malformed stored row is rejected",
                  0.5, e4,
                  "" if e4 else "the row with no text field was not reported as "
                                "tool_result_rejected"))

        r = run_app(work, TOPIC, "neverstop", timeout=LOOP_TIMEOUT)
        cap = probe.get("max_tool_steps") if isinstance(probe.get("max_tool_steps"), int) else None
        ceiling = min(cap, HARD_STEP_CEILING) if cap else HARD_STEP_CEILING
        e5 = (not r.timed_out) and 0 < r.calls <= ceiling + 1
        add(Check("E", "stub:neverstop -> terminates within the documented cap",
                  0.5, e5,
                  "" if e5 else
                  (f"did not terminate within {LOOP_TIMEOUT}s" if r.timed_out else
                   f"{r.calls} model call(s) against a declared cap of "
                   f"{cap if cap else 'none'}")))

        # ---- Group F: duplicates (0.5) ----------------------------------
        set_corpus(work, CLEAN_DOCS, pristine)
        run_app(work, TOPIC, "ok")
        first = read_store(work)
        r = run_app(work, TOPIC, "ok")
        second = r.questions

        texts = [normalise(q.get("text", "")) for q in second if q.get("text")]
        f1 = (len(texts) == len(set(texts))
              and len(second) <= len(first)
              and "duplicate_blocked" in r.event_names)
        add(Check("F", "The same run twice stores nothing new and says so",
                  0.5, f1,
                  "" if f1 else "; ".join(filter(None, [
                      "the store holds two identical questions"
                      if len(texts) != len(set(texts)) else "",
                      "the second run added a question"
                      if len(second) > len(first) else "",
                      "no duplicate_blocked event"
                      if "duplicate_blocked" not in r.event_names else "",
                  ]))))

    # ---- Group F: the committed trace (0.5), read from the repo itself ----
    trace = repo / "samples" / "tool_trace.jsonl"
    records, bad = read_jsonl(trace)
    calls = sum(len(x.get("tool_calls") or []) for x in records
                if isinstance(x.get("tool_calls"), list))
    results = sum(1 for x in records if x.get("role") == "tool")
    problems = []
    if not trace.exists():
        problems.append("samples/tool_trace.jsonl missing")
    else:
        if bad:
            problems.append(f"{bad} line(s) do not parse")
        if not records or not all("role" in x for x in records):
            problems.append("a line has no role")
        if not calls:
            problems.append("no tool calls in the trace")
        elif calls != results:
            problems.append(f"{calls} tool call(s) against {results} tool result(s)")
    add(Check("F", "samples/tool_trace.jsonl: well-formed, counts agree",
              0.5, not problems, "; ".join(problems[:2])))

    return res


# --------------------------------------------------------------------------

def render(res: Result) -> str:
    out = [f"# Lab 6: {res.repo}", "",
           f"**Harness: {res.awarded} / {res.total}**  ",
           "Read by a human: 6.5. Lab total: 15.0", "",
           "## Gates", "",
           "A failing gate is not a lost fraction of a mark.", "",
           "| Gate | Result | Note |", "|---|:-:|---|"]
    for g in res.gates:
        out.append(f"| {g.name} | {'PASS' if g.passed else 'FAIL'} | {g.note} |")

    out += ["", "## Automated marks", "",
            "| | Check | Marks | Result | Note |",
            "|---|---|--:|:-:|---|"]
    for c in res.checks:
        out.append(f"| {c.group} | {c.name} | {c.marks} | "
                   f"{'PASS' if c.passed else 'FAIL'} | {c.note} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--all", action="store_true",
                    help="treat path as a directory of student repos")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    repos = sorted(p for p in root.iterdir() if p.is_dir()) if args.all else [root]

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    summary = []

    if SELF_CHECK:
        print("[self-check mode] client.py and stub_client.py are taken as-is.\n"
              "The marking run uses the supplied originals.\n")

    for repo in repos:
        res = check_repo(repo)
        print(render(res))
        print()
        (outdir / f"{res.repo}.md").write_text(render(res), encoding="utf-8")
        summary.append({"repo": res.repo, "awarded": res.awarded,
                        "total": res.total,
                        "gates": [g.__dict__ for g in res.gates],
                        "checks": [c.__dict__ for c in res.checks]})

    (outdir / "summary.json").write_text(json.dumps(summary, indent=2),
                                         encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
