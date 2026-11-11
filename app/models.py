"""Pydantic models mirroring SPEC section 4.

Deliberate choices:
- Dates are ISO strings ("2024-01", "2024-01-31") validated by a helper, not
  by `date`, so a resume can express month precision without fake day numbers.
- "Present" is allowed as an end date for the current role.
- Bullets keep `raw_facts` (what the user said) and `text` (polished). The fact
  guard in Stage 7 checks text against raw_facts, and Stage 6 tailors from
  raw_facts only, so wording never drifts.
"""

from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PRESENT = "Present"

# Everything a person actually types for "I am still here". Each normalises to
# the single stored value `PRESENT`, so the renderer has one thing to match and a
# resume cannot end up saying "Current - Ongoing".
PRESENT_WORDS = {
    "present", "current", "currently", "now", "ongoing", "till date",
    "to date", "presently", "still", "todate", "till now", "to present",
    "ongoing.", "present-", "to date.", "till now.", "present",
    "still going", "still working", "to present.", "till present",
}

_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12,
    "december": 12,
}

# What a person actually types, so the field does not have to be ISO. Anything
# here is normalised to "YYYY-MM" (or `PRESENT`) on the way in, so nothing
# downstream has to know that "Jul 2026" and "2026-07" mean the same month.
# A day, kept only when the user wrote one. The ordinal suffix ("26th") is
# allowed because people write it and it carries no ambiguity.
_DAY = r"(?:(?P<d1>0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s*[-/.]\s*)?"

_MONTH_FIRST_RE = re.compile(
    r"^(?:"
    r"(?P<mname>[A-Za-z]{3,9})\.?,?\s*[-/ ]?\s*(?P<y1>\d{4})"   # July 2026, Jul-2026
    r"|(?P<y2>\d{4})\s*[-/. ]\s*(?P<mnum>0?[1-9]|1[0-2])"      # 2026-07, 2026/7
    # The day goes here and only here. It is attached to the month-first numeric
    # form so "07/2026" cannot be read as day 07 of month 2026 -- which it was,
    # silently producing a bare year.
    r"|" + _DAY + r"(?P<mon>0?[1-9]|1[0-2])\s*[-/.]\s*(?P<y3>\d{4})"  # 07/2026
    r"|(?P<y4>\d{4})\s*[-/. ]\s*(?P<mname2>[A-Za-z]{3,9})"      # 2026 July
    r"|(?P<y5>\d{4})"                                           # 2026
    r")\.?$"
)

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Characters that must never reach a renderer. Tab and newline are allowed
# because multi-line text is legitimate.
INVISIBLE = (
    {chr(c) for c in range(0x00, 0x20)} - {"\t", "\n", "\r"}
    | {chr(0x7F)}
    | {chr(c) for c in range(0x80, 0xA0)}              # C1 controls
    | {chr(c) for c in range(0x200B, 0x2010)}          # zero-width
    | {chr(c) for c in range(0x202A, 0x202F)}          # bidi overrides
    | {chr(c) for c in range(0x2066, 0x206A)}          # bidi isolates
    | {chr(0xFEFF)}                                    # BOM / zero-width nbsp
)

# A resume has a finite number of entries; unbounded lists are a resource
# problem, not a feature.
MAX_LIST = 60
MAX_BULLETS = 12
MAX_LINKS = 20


def new_id() -> str:
    return uuid.uuid4().hex


DATE_HELP = (
    "Write it as YYYY-MM (2026-07), or as July 2026 / Jul 2026 / 07/2026 / "
    "2026 / 2026-07-15. For an ongoing role write Present, Current, Now, "
    "Ongoing or Till date."
)


def normalise_date(value: str, field: str = "date") -> str:
    """Accept what a person types; store one canonical form.

    A date field that rejects "July 2026" gets "July 2026" typed into it anyway,
    and the user is told to fix a value they believe is right. So the natural
    forms are parsed here and stored as `YYYY-MM` (month precision, no invented
    day) or as `PRESENT`.

    Everything here is a normalisation, never a guess about what the user meant:
    an unparseable value is rejected with an error that shows the accepted forms
    rather than being turned into something plausible.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a date, not blank. " + DATE_HELP)
    raw = value.strip()
    low = raw.lower().strip(" .")

    if low in PRESENT_WORDS:
        return PRESENT
    if raw == PRESENT:
        return PRESENT

    if _MONTH_RE.match(raw):
        return raw

    # A full ISO date keeps its day: the user gave one.
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        try:
            date.fromisoformat(raw)
        except ValueError:
            raise ValueError(
                f"{raw!r} is not a real date ({field}). " + DATE_HELP
            ) from None
        return raw

    m = _MONTH_FIRST_RE.match(raw)
    if m:
        g = m.groupdict()
        if g.get("y5"):
            # A bare year is a year, not January. Storing 2026-01 would print a
            # month the user never wrote.
            return g["y5"]

        month: int | None = None
        if g.get("mnum"):
            month = int(g["mnum"])
        elif g.get("mon"):
            month = int(g["mon"])
        else:
            name = (g.get("mname") or g.get("mname2") or "").lower().rstrip(".")
            month = _MONTH_NAMES.get(name)
        year = g.get("y1") or g.get("y2") or g.get("y3") or g.get("y4")
        if month and year:
            if not 1 <= month <= 12:
                # "13/2026" reads as month 13 to the regex. Rejected rather than
                # wrapped into January, which would be a date nobody typed.
                raise ValueError(
                    f"{raw!r} has {month} as its month ({field}). " + DATE_HELP
                )
            if g.get("d1"):
                # The user wrote a day, so it is kept -- but only if the whole
                # date is real. "31/02/2026" is rejected rather than rolled over.
                iso = f"{int(year):04d}-{month:02d}-{int(g['d1']):02d}"
                try:
                    date.fromisoformat(iso)
                except ValueError:
                    raise ValueError(
                        f"{raw!r} is not a real date ({field}). " + DATE_HELP
                    ) from None
                return iso
            return f"{int(year):04d}-{month:02d}"

    raise ValueError(
        f"{raw!r} is not a date I can read ({field}). " + DATE_HELP
    )


def validate_date_str(value: str, field: str) -> str:
    """Accept the natural forms and the ISO ones; store the canonical one."""
    return normalise_date(value, field)


def _as_comparable(value: str) -> date:
    """Widen a stored date to a real date for comparison only.

    A bare year and a month-precision value both become the first day of the
    earliest thing they could mean. That is not a claim about the date -- the
    stored value keeps the precision the user typed -- it just makes "did these
    two overlap" answerable. Used only for the ordering check.
    """
    if _MONTH_RE.match(value):
        value = f"{value}-01"
    elif re.match(r"^\d{4}$", value):
        value = f"{value}-01-01"
    return date.fromisoformat(value)


def _as_range_point(value: str) -> date:
    """A date for comparing a range, with the open end sorted after every real
    date.

    `Present` is what an ongoing role ends with, so it names a position rather
    than a day. `date.max` gives it one that needs no special case in the
    comparison below, which is the whole point: an earlier version only treated
    the *end* as open, so a start of `Present` fell through to the ISO parser
    and was refused by the very range check meant to make sense of it.
    """
    if value.strip().lower() in PRESENT_WORDS:
        return date.max
    return _as_comparable(value)


def validate_date_range(start: str, end: str | None) -> None:
    """end must be 'Present'/None or not before start.

    A range that opens with the open end and closes on a real date is
    contradictory -- still going, but finished -- and it is nearly always the two
    dates typed the wrong way round. The message says so, because a generic
    "comes before" sends people to look at the wrong field.
    """
    if not end:
        return
    try:
        sd = _as_range_point(start)
        ed = _as_range_point(end)
    except ValueError:
        raise ValueError(
            f"{start!r} .. {end!r} is not a date range I can read. " + DATE_HELP
        ) from None
    if ed < sd:
        if sd == date.max:
            raise ValueError(
                f"the start date {start!r} means 'still going', but the end date "
                f"{end!r} is a real day. If the role is current, put the start "
                f"month in start and {PRESENT!r} in end. If it has ended, "
                f"the end date belongs in start and the start date in end."
            )
        raise ValueError(
            f"the end date {end!r} comes before the start date {start!r}"
        )


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def _reject_invisible_chars(cls, v):
        """Reject control / invisible characters in any text field.

        They survive JSON happily but are hostile in a rendered document: bidi
        overrides (U+202E) can visually reverse text, zero-width characters
        break keyword matching, and NUL and other C0 bytes corrupt PDF output.
        Rejecting with a clear message beats stripping, because the user
        cannot see these characters to begin with.
        """
        if isinstance(v, str):
            bad = sorted({f"U+{ord(c):04X}" for c in v if c in INVISIBLE})
            if bad:
                raise ValueError(
                    "contains characters that are invisible or unsafe in a "
                    f"document: {', '.join(bad)}"
                )
        return v


# --------------------------------------------------------------------------
# Contact / shared building blocks
# --------------------------------------------------------------------------


class Link(StrictModel):
    label: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=1, max_length=500)


class Grade(StrictModel):
    value: str = Field(min_length=1, max_length=40)
    # Scale is required so a bare number is never rendered (RULES.md section 9).
    scale: str = Field(min_length=1, max_length=40)


class Bullet(StrictModel):
    id: str = Field(default_factory=new_id)
    raw_facts: str = Field(default="", max_length=4000)
    text: str = Field(min_length=1, max_length=2000)
    metrics: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    tags: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    tools: list[str] = Field(default_factory=list, max_length=MAX_LIST)


class Contact(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    phone: str = Field(min_length=5, max_length=40)
    city: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=120)
    links: list[Link] = Field(default_factory=list, max_length=MAX_LINKS)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str) -> str:
        if "@" not in v or v.startswith("@") or v.endswith("@") or "." not in v.split("@")[-1]:
            raise ValueError(f"email is not a valid address: {v!r}")
        return v


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------


class Education(StrictModel):
    id: str = Field(default_factory=new_id)
    institution: str = Field(min_length=1, max_length=300)
    degree: str = Field(default="", max_length=200)
    field: str = Field(default="", max_length=200)
    start: str
    end: str | None = None
    grade: Grade | None = None
    coursework: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    notes: str = ""

    @field_validator("start")
    @classmethod
    def _start(cls, v: str) -> str:
        return validate_date_str(v, "education.start")

    @field_validator("end")
    @classmethod
    def _end(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_date_str(v, "education.end")

    @model_validator(mode="after")
    def _range(self) -> "Education":
        validate_date_range(self.start, self.end)
        return self


class Experience(StrictModel):
    id: str = Field(default_factory=new_id)
    org: str = Field(min_length=1, max_length=300)
    role: str = Field(min_length=1, max_length=300)
    type: Literal["job", "internship", "freelance"] = "job"
    location: str = Field(default="", max_length=200)
    start: str
    end: str | None = None
    bullets: list[Bullet] = Field(default_factory=list, max_length=MAX_BULLETS)

    @field_validator("start")
    @classmethod
    def _start(cls, v: str) -> str:
        return validate_date_str(v, "experience.start")

    @field_validator("end")
    @classmethod
    def _end(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_date_str(v, "experience.end")

    @model_validator(mode="after")
    def _range(self) -> "Experience":
        validate_date_range(self.start, self.end)
        return self


class Project(StrictModel):
    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=300)
    role: str = Field(default="", max_length=300)
    links: list[Link] = Field(default_factory=list, max_length=MAX_LINKS)
    start: str | None = None
    end: str | None = None
    tech: list[str] = Field(default_factory=list, max_length=MAX_LIST)
    bullets: list[Bullet] = Field(default_factory=list, max_length=MAX_BULLETS)

    @model_validator(mode="after")
    def _range(self) -> "Project":
        if self.start:
            self.start = validate_date_str(self.start, "project.start")
        if self.end is not None:
            self.end = validate_date_str(self.end, "project.end")
        if self.start:
            validate_date_range(self.start, self.end)
        return self


class SkillGroup(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    items: list[str] = Field(default_factory=list, max_length=MAX_LIST)


class SimpleItem(StrictModel):
    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=300)
    issuer: str = Field(default="", max_length=200)
    date: str | None = None
    url: str = Field(default="", max_length=500)
    details: str = Field(default="", max_length=2000)

    @field_validator("date")
    @classmethod
    def _date(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_date_str(v, "date")


# --------------------------------------------------------------------------
# Optional personal details (legacy Indian biodata; omit by default)
# --------------------------------------------------------------------------


class BoardResult(StrictModel):
    board: str = Field(default="", max_length=200)
    subject: str = Field(default="", max_length=200)
    year: str | None = None
    score: str = Field(default="", max_length=120)

    @field_validator("year")
    @classmethod
    def _year(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.match(r"^(19|20)\d{2}$", v):
            raise ValueError(f"year must be YYYY; got {v!r}")
        return v


class PersonalDetails(StrictModel):
    """Stored on the profile, rendered only when a Version opts in.

    Never auto-added and never scored (SPEC section 4).
    """

    photo_path: str = Field(default="", max_length=500)
    date_of_birth: str | None = None
    gender: str = Field(default="", max_length=60)
    marital_status: str = Field(default="", max_length=60)
    fathers_name: str = Field(default="", max_length=200)
    class_10: BoardResult | None = None
    class_12: BoardResult | None = None

    @field_validator("date_of_birth")
    @classmethod
    def _dob(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_date_str(v, "personal_details.date_of_birth")


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


class Profile(StrictModel):
    id: str = Field(default_factory=new_id)
    contact: Contact
    summary: str = Field(default="", max_length=4000)
    # One free-text line, rendered as "Interests: ..." at the very end of the
    # sheets template. Deliberately a string, not a list: the source describes a
    # single line, and a structured list would invite more than that.
    interests: str = Field(default="", max_length=500)
    education: list[Education] = Field(default_factory=list, max_length=MAX_LIST)
    experience: list[Experience] = Field(default_factory=list, max_length=MAX_LIST)
    projects: list[Project] = Field(default_factory=list, max_length=MAX_LIST)
    skills: list[SkillGroup] = Field(default_factory=list, max_length=MAX_LIST)
    certifications: list[SimpleItem] = Field(default_factory=list, max_length=MAX_LIST)
    achievements: list[SimpleItem] = Field(default_factory=list, max_length=MAX_LIST)
    extracurriculars: list[SimpleItem] = Field(default_factory=list, max_length=MAX_LIST)
    publications: list[SimpleItem] = Field(default_factory=list, max_length=MAX_LIST)
    personal_details: PersonalDetails = Field(default_factory=PersonalDetails)


# --------------------------------------------------------------------------
# Version / JobDescription / Application
# --------------------------------------------------------------------------


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    passed: bool = False
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Version(StrictModel):
    id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=200)
    profile_snapshot: Profile
    jd_id: str | None = None
    # Which resume template to render with. Defined in rules.json
    # resume_templates; unknown values fall back to the default.
    template: str = Field(default="blank", max_length=40)
    created_at: str = Field(default_factory=lambda: date.today().isoformat())
    validation_report: ValidationReport | None = None
    # Legacy biodata rendering is opt-in per version (SPEC section 4).
    include_personal_details: bool = False


class VersionSummary(StrictModel):
    """One row of a version list -- deliberately NOT a Version.

    `Version` requires `profile_snapshot`, which is the entire resume. Listing
    twenty snapshots would ship twenty complete resumes to a listbox, and the
    database query does not even read the column. A version browser needs the
    index fields and nothing else, so that is what this carries.
    """

    id: str
    name: str
    template: str = "blank"
    created_at: str = ""
    jd_id: str | None = None


class JobParsed(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = ""
    seniority: str = ""
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class JobDescription(StrictModel):
    id: str = Field(default_factory=new_id)
    raw_text: str = Field(min_length=1)
    parsed: JobParsed = Field(default_factory=JobParsed)


class Application(StrictModel):
    id: str = Field(default_factory=new_id)
    company: str = Field(min_length=1, max_length=300)
    role: str = Field(min_length=1, max_length=300)
    jd_id: str | None = None
    version_id: str | None = None
    applied_on: str | None = None
    source: str = Field(default="", max_length=120)
    status: Literal[
        "draft", "applied", "screening", "interview", "offer", "rejected", "withdrawn"
    ] = "draft"
    notes: str = Field(default="", max_length=8000)

    @field_validator("applied_on")
    @classmethod
    def _applied(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return validate_date_str(v, "applied_on")
