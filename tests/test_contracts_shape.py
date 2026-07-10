"""Direct guards for the frozen shared contracts (bugfix-loop T1).

`app/contracts.py` is the constitution every module imports, and
`web/lib/types.ts` is its hand-maintained TypeScript mirror ("keep
byte-identical" per its header) — yet nothing asserted either shape directly:
the audit found the contract guarded only via incidental `model_validate`
calls, and the TS mirror guarded by nothing at all. A drift (renamed field,
new appliance, new frame field) would silently mis-deserialize on the client.

The parity tests parse types.ts textually — no TS toolchain required.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import BaseModel, ValidationError

from app.contracts import (
    Appliance,
    AudioFrame,
    CaseFile,
    Customer,
    SessionBridge,
    StateFrame,
    Symptom,
    TranscriptFrame,
    UserTextFrame,
)

REPO = Path(__file__).resolve().parents[1]
TYPES_TS = (REPO / "web" / "lib" / "types.ts").read_text()

APPLIANCES = ("washer", "dryer", "refrigerator", "dishwasher", "oven", "hvac")


# --- python-side shape guards -------------------------------------------------


def test_appliance_literal_is_pinned_to_the_six_types() -> None:
    assert get_args(Appliance) == APPLIANCES


def test_case_file_defaults() -> None:
    cf = CaseFile()
    assert cf.appliance_type is None
    assert cf.brand is None and cf.model is None
    assert cf.symptoms == [] and cf.steps_given == []
    assert cf.safety_flag is False
    assert cf.customer == Customer()
    assert cf.customer.name is None and cf.customer.zip is None and cf.customer.email is None


def test_case_file_field_set_is_frozen() -> None:
    assert set(CaseFile.model_fields) == {
        "appliance_type",
        "brand",
        "model",
        "symptoms",
        "safety_flag",
        "steps_given",
        "customer",
    }


def test_case_file_rejects_unknown_appliance() -> None:
    with pytest.raises(ValidationError):
        CaseFile(appliance_type="toaster")


def test_frame_type_discriminants_are_fixed() -> None:
    assert UserTextFrame(text="hi").type == "user_text"
    assert TranscriptFrame(role="agent", text="hi").type == "transcript"
    assert AudioFrame(chunk="aGk=", seq=0).type == "audio"
    assert StateFrame(case_file=CaseFile()).type == "state"


def test_audio_frame_format_literal() -> None:
    assert AudioFrame(chunk="aGk=", seq=1, format="pcm24k").format == "pcm24k"
    assert AudioFrame(chunk="aGk=", seq=1, format="mp3").format == "mp3"
    assert AudioFrame(chunk="aGk=", seq=1).format is None
    with pytest.raises(ValidationError):
        AudioFrame(chunk="aGk=", seq=1, format="wav")


def test_frames_round_trip_their_wire_shape() -> None:
    for frame in (
        UserTextFrame(text="hello"),
        TranscriptFrame(role="user", text="hello"),
        AudioFrame(chunk="aGk=", seq=3, format="pcm24k"),
        StateFrame(case_file=CaseFile(appliance_type="dryer", safety_flag=True)),
    ):
        assert type(frame).model_validate(frame.model_dump()) == frame


def test_session_bridge_is_runtime_checkable() -> None:
    class Impl:
        async def receive_user_utterance(self, text, audio_seq=None): ...
        async def emit_transcript(self, role, text): ...
        async def emit_audio(self, chunk): ...

    class Partial:
        async def emit_audio(self, chunk): ...

    assert isinstance(Impl(), SessionBridge)
    assert not isinstance(Partial(), SessionBridge)


# --- web/lib/types.ts parity ----------------------------------------------------


def _ts_interface_fields(name: str) -> set[str]:
    block = re.search(rf"export interface {name} \{{(.*?)\n\}}", TYPES_TS, re.DOTALL)
    assert block, f"interface {name} not found in web/lib/types.ts"
    fields = set()
    for line in block.group(1).splitlines():
        line = line.strip()
        if line.startswith(("//", "/*", "*")) or not line:
            continue
        m = re.match(r"(\w+)\??:", line)
        if m:
            fields.add(m.group(1))
    return fields


_MIRRORED_MODELS: list[type[BaseModel]] = [
    Symptom,
    Customer,
    CaseFile,
    UserTextFrame,
    TranscriptFrame,
    AudioFrame,
    StateFrame,
]


@pytest.mark.parametrize("model", _MIRRORED_MODELS, ids=lambda m: m.__name__)
def test_types_ts_mirrors_contract_fields(model: type[BaseModel]) -> None:
    assert _ts_interface_fields(model.__name__) == set(model.model_fields), (
        f"web/lib/types.ts interface {model.__name__} drifted from app/contracts.py — "
        "update the mirror (its header requires it stays identical)"
    )


def test_types_ts_appliance_union_matches() -> None:
    block = re.search(r"export type Appliance =(.*?);", TYPES_TS, re.DOTALL)
    assert block, "Appliance type alias not found in web/lib/types.ts"
    ts_values = re.findall(r'"(\w+)"', block.group(1))
    assert tuple(ts_values) == APPLIANCES


def test_types_ts_empty_case_file_covers_every_field() -> None:
    block = re.search(r"EMPTY_CASE_FILE: CaseFile = \{(.*?)\n\};", TYPES_TS, re.DOTALL)
    assert block, "EMPTY_CASE_FILE not found in web/lib/types.ts"
    keys = set(re.findall(r"^\s*(\w+):", block.group(1), re.MULTILINE))
    assert keys == set(CaseFile.model_fields)
