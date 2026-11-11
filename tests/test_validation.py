"""Acceptance: invalid profiles are rejected with a clear error."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models import Profile


def _minimal(**overrides) -> dict:
    payload = {
        "contact": {
            "name": "Anon",
            "email": "anon@example.com",
            "phone": "+91 98765 43210",
        }
    }
    payload.update(overrides)
    return payload


# --- model-level ---------------------------------------------------------


def test_missing_name_is_rejected() -> None:
    payload = _minimal()
    del payload["contact"]["name"]
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    message = str(exc.value)
    assert "name" in message
    assert "contact" in message


def test_missing_email_is_rejected() -> None:
    payload = _minimal()
    del payload["contact"]["email"]
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_missing_contact_block_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate({})


def test_bad_date_is_rejected() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "banana", "end": "Present"}
        ]
    )
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    assert "banana" in str(exc.value)
    assert "YYYY-MM" in str(exc.value)


def test_bad_date_day_is_rejected() -> None:
    payload = _minimal(
        education=[
            {"institution": "BITS Pilani", "start": "2022-13", "end": "2023-01"}
        ]
    )
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_end_before_start_is_rejected() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "2024-01", "end": "2023-01"}
        ]
    )
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    assert "before" in str(exc.value)


def test_present_is_allowed_as_end_date() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "2022-07", "end": "Present"}
        ]
    )
    assert Profile.model_validate(payload).experience[0].end == "Present"


# --- Present is the open end, not a date -------------------------------------
# `Present` is what an ongoing role ends with, so it has no calendar position of
# its own. Only the *end* was treated as open: a start of `Present` fell through
# to the ISO parser and was refused, even though the parser had just accepted it.
# One comparison with `Present` meaning "after every real date" covers both
# ends, and the range stays a range.


@pytest.mark.parametrize(
    "start, end",
    [
        ("Present", "Present"),
        ("Present", None),
        ("Current", "Present"),
        ("Present", "Ongoing"),
    ],
)
def test_present_in_either_position_is_the_open_end(start, end) -> None:
    entry = {"org": "PayFlow", "role": "Backend Engineer", "start": start}
    if end is not None:
        entry["end"] = end
    entry = Profile.model_validate(_minimal(experience=[entry])).experience[0]
    assert entry.start == "Present"
    # Any word for "still going" is stored as the one label the template prints.
    assert entry.end == (end if end is None else "Present")


@pytest.mark.parametrize("present_word", ["Current", "Now", "Ongoing", "Till date"])
def test_a_range_that_is_still_going_is_not_backwards(present_word) -> None:
    """The common case: a real start, no end, and the word for "still going"."""
    profile = Profile.model_validate(_minimal(
        experience=[{"org": "PayFlow", "role": "Backend Engineer",
                     "start": "2022-07", "end": present_word}]
    ))
    assert profile.experience[0].end == "Present"


def test_a_range_starting_present_and_ending_in_the_past_says_so() -> None:
    """Present cannot both open a range and close it earlier: a range still going
    has not ended. The message has to say which field is the problem, because the
    fix is to swap them and a generic "before" complaint sends people looking in
    the wrong place."""
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(_minimal(
            experience=[{"org": "PayFlow", "role": "Backend Engineer",
                         "start": "Present", "end": "2024-06"}]
        ))
    message = str(exc.value)
    assert "Present" in message
    assert "start" in message.lower()


# --- the words people actually type for a date -----------------------------
# A date field that rejects "July 2026" gets "July 2026" typed into it anyway,
# and then refuses a save over a value the user believes is right. So the
# natural forms are accepted and stored canonically.


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("July 2026", "2026-07"),
        ("july 2026", "2026-07"),
        ("Jul 2026", "2026-07"),
        ("JUL 2026", "2026-07"),
        ("Jul-2026", "2026-07"),
        ("Jul. 2026", "2026-07"),
        ("July, 2026", "2026-07"),
        ("Sept 2026", "2026-09"),
        ("  July 2026  ", "2026-07"),
        ("Dec 2025.", "2025-12"),
        ("07/2026", "2026-07"),
        ("7/2026", "2026-07"),
        ("2026/7", "2026-07"),
        ("2026 July", "2026-07"),
        ("2026-07", "2026-07"),
        ("2026-07-15", "2026-07-15"),
        ("15/07/2026", "2026-07-15"),
        ("2019", "2019"),
    ],
)
def test_a_natural_date_is_accepted_and_stored_canonically(typed: str, stored: str) -> None:
    payload = _minimal(
        experience=[{"org": "PayFlow", "role": "Backend Engineer", "start": typed}]
    )
    assert Profile.model_validate(payload).experience[0].start == stored


def test_a_bare_year_does_not_become_january() -> None:
    """Storing 2019 as 2019-01 would print a month nobody typed."""
    payload = _minimal(
        education=[{"institution": "BITS Pilani", "start": "2019"}]
    )
    assert Profile.model_validate(payload).education[0].start == "2019"


@pytest.mark.parametrize(
    "typed",
    ["Current", "current", "Now", "Ongoing", "Till date", "to date",
     "currently", "Till now", "to present", "ongoing."],
)
def test_every_word_for_still_working_stores_the_same_value(typed: str) -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "2022-07", "end": typed}
        ]
    )
    assert Profile.model_validate(payload).experience[0].end == "Present"


@pytest.mark.parametrize(
    "typed",
    ["soon", "next month", "Julyy 2026", "13/2026", "31/02/2026", "202607",
     "20267", "29/02/2025", "2026-13", "2026-07-32"],
)
def test_a_date_the_user_cannot_have_meant_is_rejected(typed: str) -> None:
    """Rejected, never rolled over. 31/02 becoming 3 March would be a date the
    user never wrote, printed on their resume."""
    payload = _minimal(
        experience=[{"org": "PayFlow", "role": "Backend Engineer", "start": typed}]
    )
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_a_rejected_date_says_what_to_type() -> None:
    """"body.experience.0.start" means nothing to the person looking at it."""
    payload = _minimal(
        experience=[{"org": "PayFlow", "role": "Backend Engineer", "start": "soon"}]
    )
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    message = str(exc.value)
    assert "2026-07" in message, "the message must show an accepted form"
    assert "July 2026" in message
    assert "Present" in message, "and the word for an ongoing role"


def test_a_bad_end_date_names_the_value_not_the_json_path() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "2024-01", "end": "Julyy 2026"}
        ]
    )
    with pytest.raises(ValidationError) as exc:
        Profile.model_validate(payload)
    message = str(exc.value)
    assert "Julyy 2026" in message
    assert "2026-07" in message, "the message must show an accepted form"


def test_unknown_field_is_rejected() -> None:
    payload = _minimal()
    payload["headline"] = "nope"
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


def test_bad_email_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Profile.model_validate(_minimal(contact={"name": "A", "email": "nope", "phone": "12345"}))


def test_bullet_text_is_required() -> None:
    payload = _minimal(
        experience=[
            {
                "org": "PayFlow",
                "role": "Backend Engineer",
                "start": "2022-07",
                "bullets": [{"raw_facts": "did a thing"}],
            }
        ]
    )
    with pytest.raises(ValidationError):
        Profile.model_validate(payload)


# --- HTTP-level ----------------------------------------------------------


def test_api_rejects_missing_name_with_field_path() -> None:
    payload = _minimal()
    del payload["contact"]["name"]
    with TestClient(app) as client:
        resp = client.put("/profile", json=payload)
    assert resp.status_code == 422
    body = resp.json()
    loc = " ".join(str(part) for part in body["detail"][0]["loc"])
    assert "contact" in loc and "name" in loc


def test_api_rejects_bad_date_with_reason() -> None:
    payload = _minimal(
        experience=[
            {"org": "PayFlow", "role": "Backend Engineer", "start": "banana", "end": "Present"}
        ]
    )
    with TestClient(app) as client:
        resp = client.put("/profile", json=payload)
    assert resp.status_code == 422
    assert "banana" in resp.text


def test_api_rejects_empty_body() -> None:
    with TestClient(app) as client:
        assert client.put("/profile", json={}).status_code == 422


def test_rejected_put_does_not_persist() -> None:
    with TestClient(app) as client:
        client.put("/profile", json={"contact": {"email": "x@y.com"}})
        assert client.get("/profile").status_code == 404
