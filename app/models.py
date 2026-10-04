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


def validate_date_str(value: str, field: str) -> str:
    """Accept YYYY-MM or YYYY-MM-DD (or the literal 'Present')."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    value = value.strip()
    if value == PRESENT:
        return value
    if _MONTH_RE.match(value):
        return value
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(
            f"{field} must be 'YYYY-MM', 'YYYY-MM-DD', or 'Present'; got {value!r}"
        ) from None
    return value


def validate_date_range(start: str, end: str | None) -> None:
    """end must be 'Present'/None or strictly after start."""
    if not end or end == PRESENT:
        return
    s = f"{start}-01" if _MONTH_RE.match(start) else start
    e = f"{end}-01" if _MONTH_RE.match(end) else end
    try:
        sd = date.fromisoformat(s)
        ed = date.fromisoformat(e)
    except ValueError:
        raise ValueError(f"unparseable date range: {start!r} .. {end!r}") from None
    if ed < sd:
        raise ValueError(f"end date {end!r} must not be before start date {start!r}")


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
