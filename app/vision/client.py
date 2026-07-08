"""GPT-4 Vision analysis (requirements.md §Decisions #2).

Chat-with-image via ``gpt-4o`` (the current GPT-4-class vision API — the
``gpt-4-vision-preview`` endpoint is retired) with a JSON-schema response. The prompt
includes the case file so the model confirms or contradicts reported symptoms rather
than diagnosing blind. Analysis is advisory: merged as evidence in ``app.vision.merge``,
the agent still runs its own decision-tree logic against it.

The OpenAI client is injectable so tests never hit the real API
(COORDINATION.md §4 stub seam).
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os

from openai import AsyncOpenAI

from app.contracts import CaseFile
from app.vision.schema import VISION_JSON_SCHEMA, VisionAnalysis

VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")

_SYSTEM_PROMPT = (
    "You are a computer-vision assistant supporting a home-appliance diagnostic call. "
    "Look at the photo and identify the appliance, brand (if visible), and any visibly "
    "damaged, worn, leaking, or abnormal parts. Compare what you see against the "
    "caller's reported symptoms — confirm or contradict them, don't invent new ones. "
    "Suggest at most a few concrete additional troubleshooting steps a technician-free "
    "caller could safely try. Respond only via the provided JSON schema."
)


def _case_file_summary(case_file: CaseFile) -> str:
    parts = [f"Appliance: {case_file.appliance_type or 'unknown'}"]
    if case_file.brand:
        parts.append(f"Brand: {case_file.brand}")
    if case_file.symptoms:
        described = "; ".join(
            f"{s.description} (onset: {s.onset}"
            + (f", error code {s.error_code}" if s.error_code else "")
            + (f", sound: {s.sound}" if s.sound else "")
            + ")"
            for s in case_file.symptoms
        )
        parts.append(f"Reported symptoms: {described}")
    else:
        parts.append("Reported symptoms: none captured yet")
    return "\n".join(parts)


def _image_data_uri(image_path: str) -> str:
    mime, _ = mimetypes.guess_type(image_path)
    mime = mime or "image/jpeg"
    with open(image_path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


async def analyze_image(
    image_path: str,
    case_file: CaseFile,
    client: AsyncOpenAI | None = None,
) -> VisionAnalysis:
    """Send the uploaded photo + case-file context to GPT-4o vision; parse the result."""
    openai_client = client or AsyncOpenAI()
    data_uri = _image_data_uri(image_path)

    response = await openai_client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _case_file_summary(case_file)},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            },
        ],
        response_format={"type": "json_schema", "json_schema": VISION_JSON_SCHEMA},
    )
    raw = response.choices[0].message.content
    return VisionAnalysis.model_validate(json.loads(raw))
