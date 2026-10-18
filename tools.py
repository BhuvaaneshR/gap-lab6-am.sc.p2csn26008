"""tools.py — the two read-only tools, as signatures for you to fill in.

Supplied and extendable. The names `topic_lookup` and `question_lookup`, the
Pydantic model names, and `get_tool_schemas()` are fixed, because the marking
script imports this module and calls them. Everything inside the function
bodies is yours.

Neither tool writes. Neither tool gets a shell. Both validate their arguments
before doing anything, and both validate their results before anything is
handed back to the model.

Every capability an agent has is a permission your code granted. There are no
others. The model can ask for anything. What it can reach is this file.

What you have to write is marked TODO. There are five of them.

Read TODO 1 first. It is the one that decides whether the other four
can be talked into anything.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

import security

# --------------------------------------------------------------------------
# The permissions this module grants. A tool may read inside DATA_DIR and
# nowhere else, whatever the model asks for.
#
# Resolved once, at import time, so that nothing which happens later can move
# it. The application reads corpus/ as well; the tools do not.
# --------------------------------------------------------------------------

DATA_DIR = Path(__file__).parent.joinpath("data").resolve()

#: The documented cap on tool round trips in one run. The brief requires this
#: number to appear in SPEC.md under Acceptance checks. Changing it is fine.
#: Removing it is not.
MAX_TOOL_STEPS = 6


# --------------------------------------------------------------------------
# Argument models. The tool schemas are generated from these.
# --------------------------------------------------------------------------

class TopicLookupArgs(BaseModel):
    """Arguments for topic_lookup.

    Note what is NOT here: there is no filename. A topic name is not a file
    name, so the model is never given the chance to choose one. The one place
    a path is built is load_data_file(), from a name you control.
    """

    query: str = Field(..., min_length=2, max_length=60,
                       description="A word or phrase to match against the client's "
                                   "approved topic names. Case-insensitive.")
    limit: int = Field(10, ge=1, le=50,
                       description="How many matching topics to return at most.")


class QuestionLookupArgs(BaseModel):
    """Arguments for question_lookup."""

    query: str = Field(..., min_length=1, max_length=200,
                       description="Text to match against questions already generated.")
    limit: int = Field(5, ge=1, le=50,
                       description="How many matches to return at most.")


# --------------------------------------------------------------------------
# Result models. A tool result is untrusted too: it came off a disk you do not
# control, in a format nobody enforced. Validate it before it goes anywhere
# near the message list.
# --------------------------------------------------------------------------

class TopicRecord(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1, max_length=200)


class QuestionRecord(BaseModel):
    id: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1, max_length=200)
    text: str = Field(..., min_length=1, max_length=2000)
    source: str = Field(..., min_length=1, max_length=300)


# --------------------------------------------------------------------------
# The allow-list
# --------------------------------------------------------------------------

class ToolRefused(Exception):
    """Raised when a tool declines to act.

    It carries nothing the model can use: no path, no traceback, no directory
    listing. "Could not read /home/you/app/data/topics.json" tells an attacker
    your user, your layout and your repository name.
    """


#: The only two files a tool may ever open. An allow-list of names, set here
#: and never built from anything the model said.
ALLOWED_FILES = ("topics.json", "generated_questions.json")


def load_data_file(name: str) -> str:
    """Open one of the two allow-listed files inside data/, and nothing else.

    This is the ONLY place in your tools where a path is built. Nothing the
    model says reaches it: `name` comes from your own code (ALLOWED_FILES),
    never from a tool argument.
    """
    if name not in ALLOWED_FILES:
        security.log_event(
            security.TOOL_ARG_REJECTED,
            where="tools.py:load_data_file",
            detail=f"refused non-allow-listed file name {name!r}",
        )
        raise ToolRefused()

    # Build under DATA_DIR, then resolve(). Resolve BEFORE comparing: a
    # symlink named topics.json could point anywhere, and a string check
    # like startswith("data") would also be true for a sibling directory
    # called "data_backup". is_relative_to() compares path components, not
    # characters, so it is not fooled by either.
    candidate = (DATA_DIR / name).resolve()
    if not candidate.is_relative_to(DATA_DIR):
        security.log_event(
            security.TOOL_ARG_REJECTED,
            where="tools.py:load_data_file",
            detail=f"resolved path for {name!r} escaped DATA_DIR",
        )
        raise ToolRefused()

    try:
        return candidate.read_text(encoding="utf-8")
    except OSError:
        security.log_event(
            security.TOOL_ARG_REJECTED,
            where="tools.py:load_data_file",
            detail=f"could not read allow-listed file {name!r}",
        )
        raise ToolRefused()


# --------------------------------------------------------------------------
# The tools
# --------------------------------------------------------------------------

def topic_lookup(**kwargs) -> dict:
    """Search the topic list the client keeps outside the application.

    Returns {"matches": [ ... ]} where each match is a validated TopicRecord.

    A traversal string handed to this tool (query="../.env") is just a topic
    nobody has: it is matched against topic NAMES, never used to build a
    path, so it matches nothing and the loop carries on. That is the point —
    the argument was never a path to begin with.
    """
    try:
        args = TopicLookupArgs.model_validate(kwargs)
    except ValidationError as exc:
        security.log_event(
            security.TOOL_ARG_REJECTED,
            where="tools.py:topic_lookup",
            detail=f"invalid arguments: {exc.error_count()} error(s)",
        )
        raise ToolRefused() from None

    try:
        raw = json.loads(load_data_file("topics.json"))
    except (ToolRefused, json.JSONDecodeError):
        raise ToolRefused()

    rows = raw.get("topics", []) if isinstance(raw, dict) else []
    query = args.query.strip().lower()

    matches: list[dict] = []
    for row in rows:
        try:
            record = TopicRecord.model_validate(row)
        except ValidationError:
            security.log_event(
                security.TOOL_RESULT_REJECTED,
                where="tools.py:topic_lookup",
                detail=f"dropped malformed row: {row!r}"[:200],
            )
            continue
        if query in record.name.lower():
            matches.append(record.model_dump())
        if len(matches) >= args.limit:
            break

    return {"matches": matches}


def question_lookup(**kwargs) -> dict:
    """Search the questions this application has already generated.

    Returns {"matches": [ ... ]} where each match is a validated QuestionRecord.

    This is how a repeat becomes a tool problem instead of a prompt problem:
    a model can call this before answering to avoid resubmitting something
    already in the store. Storage itself still prevents duplicates even if
    the model never calls this (see main.py) — a tool the model *may*
    consult is not a guarantee, because the model can simply forget to.
    """
    try:
        args = QuestionLookupArgs.model_validate(kwargs)
    except ValidationError as exc:
        security.log_event(
            security.TOOL_ARG_REJECTED,
            where="tools.py:question_lookup",
            detail=f"invalid arguments: {exc.error_count()} error(s)",
        )
        raise ToolRefused() from None

    try:
        raw = json.loads(load_data_file("generated_questions.json"))
    except (ToolRefused, json.JSONDecodeError):
        raise ToolRefused()

    rows = raw.get("questions", []) if isinstance(raw, dict) else []
    query = args.query.strip().lower()

    matches: list[dict] = []
    for row in rows:
        try:
            record = QuestionRecord.model_validate(row)
        except ValidationError:
            security.log_event(
                security.TOOL_RESULT_REJECTED,
                where="tools.py:question_lookup",
                detail=f"dropped malformed row id={row.get('id', '?')!r}: "
                        f"fails QuestionRecord",
            )
            continue
        if query in record.text.lower() or query in record.topic.lower():
            matches.append(record.model_dump())
        if len(matches) >= args.limit:
            break

    return {"matches": matches}


# --------------------------------------------------------------------------
# The schemas the model sees
# --------------------------------------------------------------------------

TOOL_FUNCTIONS = {
    "topic_lookup": topic_lookup,
    "question_lookup": question_lookup,
}

TOOL_ARGS = {
    "topic_lookup": TopicLookupArgs,
    "question_lookup": QuestionLookupArgs,
}


TOOL_DESCRIPTIONS = {
    "topic_lookup": (
        "Search the client's approved topic list by name. Use this to check "
        "whether a topic you are about to write questions for is one the "
        "client actually wants, or to find the closest approved topic name. "
        "Read-only; does not accept a file path, only a search phrase."
    ),
    "question_lookup": (
        "Search the questions this application has already generated, by "
        "topic or by text. Use this before writing a new question, to avoid "
        "proposing one that already exists. Read-only; does not accept a "
        "file path, only a search phrase."
    ),
}


def get_tool_schemas() -> list[dict]:
    """The tool schemas, in OpenAI function-calling form.

    The "parameters" value comes from each Pydantic model's own
    model_json_schema(), not a hand-written dict: a hand-written copy would
    silently drift from TopicLookupArgs/QuestionLookupArgs the first time a
    field changes here without the schema being updated to match.
    """
    schemas = []
    for name, model in TOOL_ARGS.items():
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS.get(
                    name, (TOOL_FUNCTIONS[name].__doc__ or "").strip()),
                "parameters": model.model_json_schema(),
            },
        })
    return schemas


def run_tool(name: str, arguments: dict) -> dict:
    """Dispatch one tool call by name.

    Returns a dict that is safe to put in a tool message. On refusal it
    returns a dict describing the refusal rather than raising, so the loop
    can tell the model it was refused and carry on instead of crashing.
    Never returns a traceback or a filesystem path.
    """
    if name not in TOOL_FUNCTIONS:
        security.log_event(
            security.TOOL_ARG_REJECTED,
            where="tools.py:run_tool",
            detail=f"refused unknown tool name {name!r}",
        )
        return {"error": "unknown_tool"}

    try:
        return TOOL_FUNCTIONS[name](**(arguments or {}))
    except ToolRefused:
        return {"error": "refused"}
    except TypeError:
        # e.g. arguments wasn't a mapping at all.
        security.log_event(
            security.TOOL_ARG_REJECTED,
            where="tools.py:run_tool",
            detail=f"{name}: arguments were not a valid mapping",
        )
        return {"error": "invalid_arguments"}
