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

from pydantic import BaseModel, Field

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
    model says reaches it: `name` comes from your own code.

    It is still written defensively, because the allow-list is the thing that
    has to hold if somebody later wires an argument into it by mistake.

    TODO 1: implement this.
      - Refuse any name not in ALLOWED_FILES.
      - Build the path under DATA_DIR, then resolve() it.
      - Resolve BEFORE you compare. A check on the string is a check on the
        wrong object: a symbolic link called topics.json can point anywhere,
        and startswith() is true for "data_backup" as well as "data".
      - Use Path.is_relative_to(), which compares path components rather than
        characters.
      - On refusal, log security.TOOL_ARG_REJECTED and raise ToolRefused.
        Do not return "" on failure: a control that returns something on
        failure is not a control.
    """
    raise NotImplementedError("TODO 1: load_data_file")


# --------------------------------------------------------------------------
# The tools
# --------------------------------------------------------------------------

def topic_lookup(**kwargs) -> dict:
    """Search the topic list the client keeps outside the application.

    Returns {"matches": [ ... ]} where each match is a validated TopicRecord.

    A traversal string handed to this tool is just a topic nobody has. It
    matches nothing, the tool returns an empty list, and the loop carries on.
    That is the point: the argument was never a path to begin with.

    TODO 2: implement this.
      - Validate kwargs with TopicLookupArgs. Invalid arguments are refused,
        logged as security.TOOL_ARG_REJECTED, and nothing is read.
      - Read the topic list through load_data_file("topics.json").
      - Match args.query against topic NAMES. Never against a filename.
      - Validate every row with TopicRecord. Drop rows that fail and log
        security.TOOL_RESULT_REJECTED.
      - Return at most args.limit matches.
    """
    raise NotImplementedError("TODO 2: topic_lookup")


def question_lookup(**kwargs) -> dict:
    """Search the questions this application has already generated.

    Returns {"matches": [ ... ]} where each match is a validated QuestionRecord.

    This is how a repeat becomes a tool problem instead of a prompt problem.

    TODO 3: implement this.
      - Validate kwargs with QuestionLookupArgs.
      - Read the store through load_data_file("generated_questions.json").
      - Validate every row with QuestionRecord. At least one row in the
        supplied store does not validate. Dropping it quietly is wrong;
        log security.TOOL_RESULT_REJECTED and say which row.
      - Return at most args.limit matches.
    """
    raise NotImplementedError("TODO 3: question_lookup")


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


def get_tool_schemas() -> list[dict]:
    """The tool schemas, in OpenAI function-calling form.

    Each entry is:

        {
          "type": "function",
          "function": {
            "name": ...,
            "description": ...,
            "parameters": <JSON schema>
          }
        }

    The description is the interface. The model never sees your function; it
    sees this text. A vague description is a bug in the tool.

    TODO 4: implement this.
      - Build one entry per tool in TOOL_ARGS.
      - The "parameters" value must come from the Pydantic model, via
        model_json_schema(). A hand-written dict scores zero here even if it
        happens to be correct, because it will drift from the model the first
        time you change a field.
      - Take the description from the function's docstring or write one here.
    """
    raise NotImplementedError("TODO 4: get_tool_schemas")


def run_tool(name: str, arguments: dict) -> dict:
    """Dispatch one tool call by name.

    Returns a dict that is safe to put in a tool message. On refusal it returns
    a dict describing the refusal rather than raising, so that the loop can
    tell the model it was refused and carry on.

    TODO 5: implement this.
      - Refuse any name not in TOOL_FUNCTIONS, and log it.
      - Call the tool, catching validation failures.
      - Never return a traceback or a filesystem path to the model.
    """
    raise NotImplementedError("TODO 5: run_tool")
