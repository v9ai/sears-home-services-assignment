"""Direct guards for the frozen shared contracts (bugfix-loop T1).

`app/contracts.py` is the constitution every module imports — nothing asserted
its shape directly: the audit found the contract guarded only via incidental
`model_validate` calls. A drift (renamed field, new appliance, new frame field)
would silently mis-deserialize downstream.

(The web UI and its `web/lib/types.ts` TypeScript mirror were removed by user
directive — the former parity tests went with them.)
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.contracts import (
    Appliance,
    AudioFrame,
    CaseFile,
    Customer,
    SessionBridge,
    StateFrame,
    TranscriptFrame,
    UserTextFrame,
)

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
