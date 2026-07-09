"""Core diagnostic tools — the agent's only way to mutate the session case file.

Auto-discovered by `app/tools/registry.py` via the module-level ``TOOLS`` list
(COORDINATION.md §1: "adding a tool = adding a file"). Signatures mirror the frozen
tool contracts in `app/contracts.py` from the LLM's point of view (the JSON schema the
model sees); internally each tool reads/writes the active turn's `CaseFile` via
`app.agent.state.get_case_file()` rather than taking a session parameter, since a
session/context argument isn't something the tool-calling model should ever have to
supply.
"""

from __future__ import annotations

from app.agent.state import get_case_file
from app.contracts import Symptom
from app.email.validation import normalize_email
from app.knowledge.loader import (
    UnknownApplianceError,
    UnknownSymptomKeyError,
    get_symptom_tree,
    load_knowledge,
)
from app.knowledge.schema import SAFETY_KEY_PREFIX

_VALID_APPLIANCES: set[str] = {
    "washer",
    "dryer",
    "refrigerator",
    "dishwasher",
    "oven",
    "hvac",
}


async def identify_appliance(appliance_type: str) -> str:
    """Record the appliance type the caller is having trouble with.

    Call this as soon as the appliance is known (washer, dryer, refrigerator,
    dishwasher, oven, or hvac). Safe to call again if the caller corrects themselves.
    """
    normalized = appliance_type.strip().lower()
    if normalized not in _VALID_APPLIANCES:
        return (
            f"'{appliance_type}' is not a supported appliance type. Valid options: "
            f"{', '.join(sorted(_VALID_APPLIANCES))}."
        )
    case_file = get_case_file()
    case_file.appliance_type = normalized  # type: ignore[assignment]
    return f"Case file updated: appliance_type={normalized}."


async def record_symptom(
    description: str,
    onset: str | None = None,
    error_code: str | None = None,
    sound: str | None = None,
) -> str:
    """Record one reported symptom (what's happening, when it started, error code, sound).

    Call once per distinct symptom the caller describes. Never call this to re-ask for
    a detail already present in the case file — check the case file in the system
    prompt first.
    """
    case_file = get_case_file()
    case_file.symptoms.append(
        Symptom(
            description=description,
            onset=onset or "unspecified",
            error_code=error_code,
            sound=sound,
        )
    )
    return f"Symptom recorded: {description!r} (onset={onset or 'unspecified'})."


async def get_troubleshooting_steps(appliance: str, symptom_key: str) -> str:
    """Fetch the deterministic troubleshooting steps for `appliance` + `symptom_key`
    (must be a key from the system prompt's vocabulary — never invent steps). A
    `safety_`-prefixed key returns a safety-escalation script: relay it verbatim and
    offer a technician instead of DIY."""
    try:
        tree = get_symptom_tree(appliance, symptom_key)
    except UnknownApplianceError:
        return f"Unknown appliance '{appliance}'."
    except UnknownSymptomKeyError:
        known = ", ".join(load_knowledge(appliance).symptoms.keys())
        return f"Unknown symptom_key '{symptom_key}' for {appliance}. Known keys: {known}."

    case_file = get_case_file()
    is_safety = symptom_key.startswith(SAFETY_KEY_PREFIX)
    numbered = [f"{i}. {step}" for i, step in enumerate(tree.steps, start=1)]
    case_file.steps_given.extend(tree.steps)
    if is_safety:
        case_file.safety_flag = True
        return (
            "SAFETY ESCALATION — do not offer any further DIY troubleshooting. "
            "Relay these steps to the caller now and then offer to schedule a "
            "technician:\n" + "\n".join(numbered)
        )
    return f"Troubleshooting steps for {appliance} / {symptom_key}:\n" + "\n".join(numbered)


async def update_case_file(
    brand: str | None = None,
    model: str | None = None,
    customer_name: str | None = None,
    customer_zip: str | None = None,
    customer_email: str | None = None,
) -> str:
    """Update case-file fields that don't have a dedicated tool: brand, model, and the
    caller's name/zip/email as they're captured. Pass only the fields you have new
    values for; omitted fields are left untouched.
    """
    case_file = get_case_file()
    updated: list[str] = []
    if brand is not None:
        case_file.brand = brand
        updated.append(f"brand={brand}")
    if model is not None:
        case_file.model = model
        updated.append(f"model={model}")
    if customer_name is not None:
        case_file.customer.name = customer_name
        updated.append(f"customer.name={customer_name}")
    if customer_zip is not None:
        case_file.customer.zip = customer_zip
        updated.append(f"customer.zip={customer_zip}")
    invalid: list[str] = []
    if customer_email is not None:
        normalized_email = normalize_email(customer_email)
        if normalized_email is None:
            invalid.append(
                f"customer.email not saved — '{customer_email}' doesn't look like a valid "
                "address; re-confirm it with the caller"
            )
        else:
            case_file.customer.email = normalized_email
            updated.append(f"customer.email={normalized_email}")
    if not updated and not invalid:
        return "No fields provided; case file unchanged."
    parts: list[str] = []
    if updated:
        parts.append("Case file updated: " + ", ".join(updated) + ".")
    if invalid:
        parts.append(" ".join(invalid) + ".")
    return " ".join(parts)


TOOLS = [identify_appliance, record_symptom, get_troubleshooting_steps, update_case_file]
