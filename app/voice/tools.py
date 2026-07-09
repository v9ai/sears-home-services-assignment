"""Pipecat function-calling tools — thin bridges onto the existing LlamaIndex tools.

This is the heart of the port. In the LlamaIndex build, a single `FunctionAgent`
(`app/agent/core.py`) ran the tool-calling loop over the plain async functions in
`app/tools/*`. Here the **Pipecat LLM service runs that loop instead**, and each tool is
re-exposed as a Pipecat `FunctionSchema` whose async handler calls the SAME
`app.tools.*` function — no business logic is reimplemented or copied.

The original tools read the live `CaseFile` / session id from `ContextVar`s
(`app/agent/state.py`) rather than taking them as parameters, exactly so the JSON schema
the LLM sees stays clean. We honor that: every handler runs inside `session.bind()`
(`app/voice/session.py`), which sets those same ContextVars for the duration of the call
— so `app/tools/*.py` is imported and used completely unmodified.

Each schema's `name`/`description`/parameters mirror the origin function's signature and
docstring (which is what LlamaIndex derived its schema from), so the model sees the same
tools it always did. Origin is noted inline on every tool.
"""

from __future__ import annotations

import json
import logging

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.llm_service import FunctionCallParams

# The ported LlamaIndex tools — imported and called AS-IS (never reimplemented).
from app.contracts import Customer
from app.tools import (
    core_tools,
    library_tools,  # RAG tool (flag-gated, see LIBRARY_RAG_ENABLED)
    scheduling_tools,
    visual_tools,
)
from app.voice.session import VoiceSession

logger = logging.getLogger("app.voice.tools")

_APPLIANCES = ["washer", "dryer", "refrigerator", "dishwasher", "oven", "hvac"]


def _handler(session: VoiceSession, fn, *, arg_names: tuple[str, ...]):
    """Build a Pipecat handler that binds the ContextVars and calls the origin `fn`.

    `arg_names` are pulled from `params.arguments` (the LLM-supplied JSON) and passed
    positionally to the origin function, mirroring its real signature. Any exception is
    turned into a spoken-safe error string so a tool failure never tears down the call
    (the original agent loop swallowed tool errors the same way).
    """

    async def handler(params: FunctionCallParams) -> None:
        kwargs = {name: params.arguments.get(name) for name in arg_names}
        try:
            with session.bind():  # sets current_case_file / current_session_id
                result = await fn(**{k: v for k, v in kwargs.items() if v is not None})
        except Exception:  # noqa: BLE001 — resilience: keep the call alive
            logger.exception("voice_tool_failed tool=%s args=%s", fn.__name__, list(kwargs))
            result = "Sorry, I hit a problem doing that — let's try again in a moment."
        await params.result_callback(result)

    return handler


def build_tools(session: VoiceSession) -> tuple[ToolsSchema, dict[str, object]]:
    """Return (ToolsSchema for the LLM context, {name: handler} to register on the LLM).

    Mirrors `app/tools/registry.get_tools()` — same tool set, same (flag-gated) RAG tool —
    but rendered as Pipecat schemas + handlers instead of LlamaIndex FunctionTools.
    """
    schemas: list[FunctionSchema] = []
    handlers: dict[str, object] = {}

    def add(schema: FunctionSchema, handler) -> None:
        schemas.append(schema)
        handlers[schema.name] = handler

    # --- core diagnostic tools -> app/tools/core_tools.py ------------------------------
    add(
        FunctionSchema(
            name="identify_appliance",
            description=(
                "Record the appliance type the caller is having trouble with. Call as "
                "soon as the appliance is known (washer, dryer, refrigerator, dishwasher, "
                "oven, or hvac). Safe to call again if the caller corrects themselves."
            ),
            properties={
                "appliance_type": {"type": "string", "enum": _APPLIANCES},
            },
            required=["appliance_type"],
        ),
        _handler(session, core_tools.identify_appliance, arg_names=("appliance_type",)),
    )
    add(
        FunctionSchema(
            name="record_symptom",
            description=(
                "Record one reported symptom (what's happening, when it started, error "
                "code, sound). Call once per distinct symptom. Never call to re-ask for a "
                "detail already in the case file."
            ),
            properties={
                "description": {"type": "string", "description": "What's happening."},
                "onset": {"type": "string", "description": "When it started, if said."},
                "error_code": {"type": "string", "description": "Any error/fault code shown."},
                "sound": {"type": "string", "description": "Any notable sound."},
            },
            required=["description"],
        ),
        _handler(
            session,
            core_tools.record_symptom,
            arg_names=("description", "onset", "error_code", "sound"),
        ),
    )
    add(
        FunctionSchema(
            name="get_troubleshooting_steps",
            description=(
                "Fetch the deterministic troubleshooting steps for a known "
                "appliance/symptom_key. symptom_key must be one listed for this appliance "
                "in the knowledge vocabulary — never invent steps. A symptom_key starting "
                "with 'safety_' is a safety-escalation script."
            ),
            properties={
                "appliance": {"type": "string", "enum": _APPLIANCES},
                "symptom_key": {"type": "string"},
            },
            required=["appliance", "symptom_key"],
        ),
        _handler(
            session, core_tools.get_troubleshooting_steps, arg_names=("appliance", "symptom_key")
        ),
    )
    add(
        FunctionSchema(
            name="update_case_file",
            description=(
                "Update case-file fields without a dedicated tool: brand, model, and the "
                "caller's name/zip/email. Pass only the fields you have new values for."
            ),
            properties={
                "brand": {"type": "string"},
                "model": {"type": "string"},
                "customer_name": {"type": "string"},
                "customer_zip": {"type": "string"},
                "customer_email": {"type": "string"},
            },
            required=[],
        ),
        _handler(
            session,
            core_tools.update_case_file,
            arg_names=("brand", "model", "customer_name", "customer_zip", "customer_email"),
        ),
    )

    # --- scheduling tools -> app/tools/scheduling_tools.py ----------------------------
    add(
        FunctionSchema(
            name="find_technicians",
            description=(
                "Find qualified technicians in a zip code with open slots. Returns up to 3 "
                "soonest open slots per technician. window is an optional free-text "
                "availability hint (e.g. 'Tuesday afternoon'). Reuse the case file's "
                "customer.zip — never re-ask for the zip if it's already captured."
            ),
            properties={
                "zip": {"type": "string"},
                "appliance_type": {"type": "string", "enum": _APPLIANCES},
                "window": {"type": "string"},
            },
            required=["zip", "appliance_type"],
        ),
        _handler(
            session,
            scheduling_tools.find_technicians,
            arg_names=("zip", "appliance_type", "window"),
        ),
    )

    # book_appointment's origin signature is (slot_id, customer, issue_summary). We do NOT
    # ask the LLM to hand back a nested Customer object over voice — we assemble it from
    # the live case file (which the caller has already filled in this call). This also
    # closes the `session_id=None` gap called out in scheduling_tools.py: the tool runs
    # inside session.bind(), so the booking is attributable to this call.
    async def _book_appointment(params: FunctionCallParams) -> None:
        customer = Customer(**session.case_file.customer.model_dump())
        try:
            with session.bind():
                result = await scheduling_tools.book_appointment(  # origin fn, unmodified
                    slot_id=params.arguments.get("slot_id"),
                    customer=customer,
                    issue_summary=params.arguments.get("issue_summary"),
                )
        except Exception:  # noqa: BLE001
            logger.exception("voice_tool_failed tool=book_appointment")
            result = json.dumps({"status": "error", "message": "Booking failed; please retry."})
        await params.result_callback(result)

    add(
        FunctionSchema(
            name="book_appointment",
            description=(
                "Atomically book a previously-offered slot. Call ONLY after the caller "
                "verbally confirmed technician + date + time with an explicit yes. "
                "issue_summary must name the appliance (washer/dryer/refrigerator/"
                "dishwasher/oven/hvac). On 'slot_taken', apologize and re-offer the "
                "alternatives; on 'confirmed', read the appointment id back."
            ),
            properties={
                "slot_id": {"type": "string"},
                "issue_summary": {"type": "string"},
            },
            required=["slot_id", "issue_summary"],
        ),
        _book_appointment,
    )

    # --- visual-diagnosis tools -> app/tools/visual_tools.py --------------------------
    add(
        FunctionSchema(
            name="send_image_upload_link",
            description=(
                "Email the caller a secure tokenized link to upload a photo of the "
                "appliance. Ask for the email, spell it back and get an explicit yes first."
            ),
            properties={"email": {"type": "string"}},
            required=["email"],
        ),
        _handler(session, visual_tools.send_image_upload_link, arg_names=("email",)),
    )
    add(
        FunctionSchema(
            name="check_image_analysis",
            description=(
                "Poll the latest photo upload for this call; fold any findings into the "
                "diagnosis once analysis is ready. Takes no arguments."
            ),
            properties={},
            required=[],
        ),
        _handler(session, visual_tools.check_image_analysis, arg_names=()),
    )

    # --- appliance-library RAG tool -> app/tools/library_tools.py (flag-gated) ---------
    # Mirrors registry.get_tools(): only registered when LIBRARY_RAG_ENABLED is truthy,
    # exactly as in the LlamaIndex build. The handler calls the same retrieval-only
    # `search_appliance_library` (Qdrant + FastEmbed, similarity_top_k=3) unchanged.
    if library_tools._flag_enabled():  # noqa: SLF001 — same predicate the origin module uses
        add(
            FunctionSchema(
                name="search_appliance_library",
                description=(
                    "Search the appliance-library knowledge base for guidance outside the "
                    "deterministic troubleshooting trees. Call ONLY after "
                    "get_troubleshooting_steps reports an unknown symptom_key — never in "
                    "place of it, and never in place of the safety interrupt. Cite the source."
                ),
                properties={"query": {"type": "string"}},
                required=["query"],
            ),
            _handler(session, library_tools.search_appliance_library, arg_names=("query",)),
        )

    return ToolsSchema(standard_tools=schemas), handlers
