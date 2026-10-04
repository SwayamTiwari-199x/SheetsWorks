"""Full under-the-hood verification against a live server.

Covers every route the project exposes, both templates, all three export
formats, the failure paths, and the security headers. Written to be read as a
report: it prints what it checked and what it found, not just pass or fail.
"""

import json
import sys
import urllib.error
import urllib.request

B = "http://127.0.0.1:" + (sys.argv[1] if len(sys.argv) > 1 else "8200")
FAILS = []
CHECKS = [0]


def norm(h):
    return {k.lower(): v for k, v in h.items()}


def call(method, path, body=None, raw=False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(B + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = r.read()
            return r.status, norm(r.headers), (payload if raw else _json(payload))
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, norm(e.headers), (payload if raw else _json(payload))


def _json(payload):
    try:
        return json.loads(payload)
    except Exception:
        return payload.decode("utf-8", "replace")


def check(label, ok, detail=""):
    CHECKS[0] += 1
    if not ok:
        FAILS.append(f"{label}: {detail}")
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   {detail}" if detail else ""))


def brief(body):
    """A validation error is unreadable as JSON on one line; name the fields."""
    try:
        return "; ".join(".".join(str(p) for p in d["loc"][1:]) + " " + d["msg"][:60]
                         for d in body["detail"][:4])
    except Exception:
        return str(body)[:140]


def head(title):
    print("\n=== " + title + " " + "=" * max(0, 58 - len(title)))


# --------------------------------------------------------------- the data

PROFILE = {
    "contact": {
        "name": "Dusht Verma", "email": "dusht@example.com",
        "phone": "+91 98765 43210", "city": "Bengaluru", "country": "India",
        "links": [{"label": "GitHub", "url": "github.com/dusht"},
                  {"label": "Portfolio", "url": "dusht.dev"}],
    },
    "summary": ("Backend engineer, three years on payments and latency work. "
                "I like problems where the bottleneck is hiding in a queue."),
    "interests": "Trail running, chess, and rebuilding mechanical keyboards.",
    "education": [{
        "institution": "Sample Institute of Technology",
        "degree": "B.E. Computer Science", "start": "2019-08", "end": "2022-06",
        "grade": {"value": "8.72", "scale": "10"},
    }],
    "experience": [{
        "org": "Sample Analytics", "role": "Backend Engineer", "type": "job",
        "start": "2022-07", "end": "Present",
        "bullets": [
            {"raw_facts": "900ms -> 240ms",
             "text": "Cut p99 checkout latency from 900ms to 240ms by adding a Redis read-through cache in front of the ledger."},
            {"raw_facts": "5 -> 12 engineers",
             "text": "Mentored 5 engineers into owning the settlement service, growing that team to 12 without extra headcount."},
            {"raw_facts": "0 -> 14 regions",
             "text": "Took settlement from a single region to 14 with no data loss and no migration downtime."},
        ],
    }],
    "projects": [{
        "name": "Shift Scheduler", "role": "Solo build",
        "links": [{"label": "Source", "url": "github.com/dusht/scheduler"}],
        "start": "2021-01", "end": "2021-06",
        "tech": ["FastAPI", "PostgreSQL", "Celery", "Redis"],
        "bullets": [{"raw_facts": "12 stores, 4h -> 30s",
                     "text": "Built a scheduler used by 12 stores to publish weekly rosters in under 30 seconds, down from 4 hours."}],
    }],
    "skills": [
        {"name": "Backend", "items": ["Python", "FastAPI", "PostgreSQL", "Redis"]},
        {"name": "Infrastructure", "items": ["Docker", "GitHub Actions", "Terraform"]},
    ],
    "certifications": [{"name": "AWS Solutions Architect Associate", "date": "2023-04"}],
    "achievements": [{"name": "Winner, Hackathon 2021"}],
    "extracurriculars": [],
    "publications": [{"name": "On shift scheduling",
                      "issuer": "Sample Journal", "date": "2022-05",
                      "details": "Peer-reviewed, cited four times."}],
}

# ---------------------------------------------------------------- health

head("health and discovery")
st, h, b = call("GET", "/health")
check("GET /health returns ok", st == 200 and b.get("status") == "ok", str(b))
st, h, b = call("GET", "/openapi.json")
paths = sorted(b["paths"])
check("openapi builds", st == 200, str(st))
# Was "exactly six". Renamed, not loosened: it is still an exact set, and it now
# names every route rather than counting them. Two were added in Stage 5b so that
# snapshots stopped being write-only.
check("the route surface is exactly what the app uses", paths == sorted([
    "/health", "/profile",
    "/versions", "/versions/{version_id}", "/versions/from-profile",
    "/export/{version_id}", "/preview",
]), str(paths))

# ---------------------------------------------------------------- profile

head("profile round trip")
st, h, b = call("GET", "/profile")
check("GET /profile before any write is 404", st == 404, str(st))

st, h, b = call("PUT", "/profile", PROFILE)
check("PUT /profile accepts a full profile", st == 200, brief(b))

st, h, b = call("GET", "/profile")
check("GET /profile returns it back", st == 200, brief(b))
if st == 200:
    check("name survived", b["contact"]["name"] == "Dusht Verma")
    check("interests survived", "Trail running" in b["interests"])
    check("both links survived", len(b["contact"]["links"]) == 2)
    check("grade stayed structured", b["education"][0]["grade"]["value"] == "8.72")
    check("bullets stayed objects", isinstance(b["experience"][0]["bullets"][0], dict))
    check("publications survived", len(b["publications"]) == 1)
    check("publication issuer survived",
          b["publications"][0]["issuer"] == "Sample Journal")

st, h, b = call("PUT", "/profile", {"contact": {"name": "X", "email": "bad", "phone": "12345"}})
check("PUT rejects a bad email", st == 422, str(st))

st, h, b = call("PUT", "/profile", {"contact": {"name": "X", "email": "a@b.com", "phone": "12345"},
                                    "bogus_field": 1})
check("PUT rejects an unknown field", st == 422, str(st))

st, h, b = call("PUT", "/profile", {"contact": {"name": "X", "email": "a@b.com", "phone": "12345"},
                                    "experience": [{"org": "o", "role": "r", "type": "job",
                                                    "start": "nonsense", "end": "Present"}]})
check("PUT rejects a malformed date", st == 422, str(st))

st, h, b = call("PUT", "/profile", {"contact": {"name": "X", "email": "a@b.com", "phone": "12345"},
                                    "summary": "hi\u202e\u0000there"})
check("PUT rejects invisible characters", st == 422, str(st))

st, h, b = call("PUT", "/profile", {"contact": {"name": "X", "email": "a@b.com", "phone": "12345"},
                                    "experience": [{"org": "o", "role": "r", "type": "job",
                                                    "start": "2020-01", "end": "Present",
                                                    "bullets": [{"raw_facts": "x", "text": "y"}] * 500}]})
check("PUT rejects an unbounded bullet list", st == 422, str(st))

deep = {"contact": {"name": "X", "email": "a@b.com", "phone": "12345"}}
for _ in range(4000):
    deep = {"contact": {"name": "X", "email": "a@b.com", "phone": "12345"}, "x": [deep]}
st, h, b = call("PUT", "/profile", deep)
check("PUT survives deeply nested json without a 500", st in (400, 422), str(st))

# restore the good profile after the abuse above
call("PUT", "/profile", PROFILE)

# ---------------------------------------------------------------- preview

head("preview")
for tpl in ("blank", "sheets"):
    st, h, b = call("POST", f"/preview?template={tpl}", PROFILE, raw=True)
    check(f"preview {tpl} renders a pdf", st == 200 and b[:4] == b"%PDF",
          f"{st} {b[:8]!r}")
    check(f"preview {tpl} reports pages", h.get("x-pages") == "1", h.get("x-pages"))
    check(f"preview {tpl} reports its budget", "x-page-limit" in h,
          f"limit={h.get('x-page-limit')}")
    check(f"preview {tpl} is no-store", h.get("cache-control") == "no-store")

st, h, b = call("POST", "/preview?template=sheets", PROFILE, raw=True)
check("sheets locks to one page", h.get("x-page-limit") == "1", h.get("x-page-limit"))
st, h, b = call("POST", "/preview?template=blank", PROFILE, raw=True)
check("blank allows two for an experienced profile",
      h.get("x-page-limit") == "2", h.get("x-page-limit"))

st, h, b = call("POST", "/preview?template=nonsense", PROFILE, raw=True)
check("an unknown template falls back rather than erroring", st == 200, str(st))

st, h, b = call("POST", "/preview", {"contact": {"name": "X", "email": "bad", "phone": "12345"}})
check("preview validates its body", st == 422, str(st))

# --------------------------------------------------------------- versions

head("versions and snapshots")
st, h, snap_blank = call("POST", "/versions/from-profile?name=Dusht%20Verma&template=blank")
check("snapshot blank", st == 201 and snap_blank["template"] == "blank", str(st))
st, h, snap_sheets = call("POST", "/versions/from-profile?name=Dusht%20Verma&template=sheets")
check("snapshot sheets", st == 201 and snap_sheets["template"] == "sheets", str(st))
check("the two snapshots have different ids", snap_blank["id"] != snap_sheets["id"])

st, h, listed = call("GET", "/versions")
check("versions can now be listed", st == 200 and isinstance(listed, list),
      f"GET /versions -> {st}")
check("the list is newest first", st == 200
      and [v["id"] for v in listed][:2] == [snap_sheets["id"], snap_blank["id"]],
      str([v["id"] for v in listed][:3]) if st == 200 else str(st))
check("a listed version carries no profile snapshot",
      st == 200 and all("profile_snapshot" not in v for v in listed),
      "a list of snapshots must not ship a list of resumes")
check("a listed version names its template",
      st == 200 and {v["template"] for v in listed} == {"blank", "sheets"},
      str(sorted({v["template"] for v in listed})) if st == 200 else "")
check("the version list is not cached", h.get("cache-control") == "no-store",
      h.get("cache-control"))

st, h, b = call("GET", f"/versions/{snap_blank['id']}")
# 405, not 404: the path exists for DELETE, so the router matches it and
# rejects the verb. Either is a refusal to serve a stored snapshot.
check("KNOWN GAP: still no way to fetch one stored version back",
      st in (404, 405), f"GET /versions/{{id}} -> {st}")

# Delete is exercised on a snapshot of its own. Deleting snap_blank here broke
# the export section below, which needs it -- and a check that quietly consumes
# the fixture a later check depends on is worse than no check.
st, h, doomed = call("POST", "/versions/from-profile?name=doomed")
check("a snapshot to delete exists", st == 201, str(st))
check("the delete route removes it", call("DELETE", f"/versions/{doomed['id']}")[0] == 204)
check("and it is gone from the list",
      all(v["id"] != doomed["id"] for v in call("GET", "/versions")[2]),
      "deleting must remove it from the listing too")
check("deleting it twice is a 404, not a silent success",
      call("DELETE", f"/versions/{doomed['id']}")[0] == 404)
check("an unknown id is a 404 too",
      call("DELETE", "/versions/nope")[0] == 404)
check("the limit is enforced and bounded",
      call("GET", "/versions?limit=1")[0] == 200
      and len(call("GET", "/versions?limit=1")[2]) == 1
      and call("GET", "/versions?limit=0")[0] == 422
      and call("GET", "/versions?limit=99999")[0] == 422,
      "an unbounded list is a way to dump the table in one response")

legacy = dict(PROFILE)
st, h, b = call("POST", "/versions", {"name": "legacy", "template": "ats",
                                      "profile_snapshot": legacy})
check("a pre-template version still saves", st == 201, str(st)[:120])
legacy_id = b["id"] if st == 201 else None

# ---------------------------------------------------------------- exports

head("exports: three formats, two templates")
exports = {}
for tpl, vid in (("blank", snap_blank["id"]), ("sheets", snap_sheets["id"])):
    for fmt in ("pdf", "docx", "txt"):
        st, h, raw = call("POST", f"/export/{vid}?format={fmt}", raw=True)
        disp = h.get("content-disposition", "")
        ctype = h.get("content-type", "")
        # The extension has to match the format; an earlier version of this
        # script hardcoded .txt and "failed" four correct filenames.
        stem = "Dusht Verma Resume" if tpl == "sheets" else "Dusht Verma"
        expect_name = f"{stem}.{fmt}"
        check(f"{tpl}/{fmt} exports", st == 200 and len(raw) > 0,
              f"{st} {len(raw)}B")
        check(f"{tpl}/{fmt} filename follows the template rule",
              f'filename="{expect_name}"' in disp, disp)
        check(f"{tpl}/{fmt} reports its page budget", "x-page-limit" in h)
        exports[(tpl, fmt)] = raw
        if fmt == "pdf":
            check(f"{tpl}/pdf is a real pdf", raw[:4] == b"%PDF", str(raw[:8]))
        if fmt == "docx":
            check(f"{tpl}/docx is a real zip", raw[:2] == b"PK", str(raw[:4]))
            check(f"{tpl}/docx mime", "wordprocessingml" in ctype, ctype)

st, h, b = call("POST", f"/export/{snap_blank['id']}?format=exe")
check("an unknown export format is rejected", st in (400, 422), str(st))

st, h, b = call("POST", "/export/nope?format=pdf")
check("exporting an unknown version is 404", st == 404, str(st))

# ------------------------------------------------- txt is the source of truth

head("text fidelity: docx and txt must agree")
import zipfile
import io
import re

txt_blank = exports[("blank", "txt")].decode("utf-8")
for fmt in ("docx",):
    z = zipfile.ZipFile(io.BytesIO(exports[("blank", fmt)]))
    xml = z.read("word/document.xml").decode("utf-8")
    plain = re.sub(r"<[^>]+>", "", xml)
    for word in ("Dusht", "Backend", "FastAPI", "PostgreSQL",
                 "Hackathon", "settlement"):
        check(f"docx carries '{word}' like txt does",
              word in plain and word in txt_blank, word)

check("txt starts with the name", txt_blank.strip().startswith("Dusht Verma"))
check("txt contains the phone", "+91 98765 43210" in txt_blank)
check("txt uses a hyphen for bullets", "- Cut p99" in txt_blank,
      repr(txt_blank[:200]))

txt_sheets = exports[("sheets", "txt")].decode("utf-8")
check("sheets hides the summary", "bottleneck is hiding" not in txt_sheets)
check("blank shows the summary", "bottleneck is hiding" in txt_blank)
check("sheets ends with the Interests line",
      txt_sheets.strip().endswith("Trail running, chess, and rebuilding mechanical keyboards."),
      repr(txt_sheets.strip()[-90:]))
check("blank does not print Interests", "Trail running" not in txt_blank)
for section in ("Work Experience", "Skills", "Education", "Achievements",
                "Publications"):
    check(f"sheets keeps '{section}'", section in txt_sheets)

# ------------------------------------------------------------- security

head("security headers and policy")
st, h, b = call("GET", "/")
page_csp = h.get("content-security-policy", "")
check("page CSP allows its own assets", "default-src 'self'" in page_csp)
check("page CSP allows the blob preview frame", "frame-src 'self' blob:" in page_csp)
check("page CSP forbids plugins", "object-src 'none'" in page_csp)
check("page is no-store", h.get("cache-control") == "no-store")
check("page is nosniff", h.get("x-content-type-options") == "nosniff")

st, h, b = call("GET", "/health")
api_csp = h.get("content-security-policy", "")
check("API CSP is locked down", "default-src 'none'" in api_csp)
check("API CSP forbids framing", "frame-ancestors 'none'" in api_csp)

st, h, b = call("GET", "/profile")
check("profile responses are no-store", h.get("cache-control") == "no-store",
      f"status={st} value={h.get('cache-control')!r} "
      f"cache-ish keys={[k for k in h if 'cach' in k.lower()]}")

for asset in ("/static/win/win95.css", "/static/win/shell.js", "/static/win/app.js"):
    st, h, b = call("GET", asset)
    check(f"{asset} is served with the page CSP",
          st == 200 and "default-src 'self'" in h.get("content-security-policy", ""))

st, h, b = call("GET", "/static/win/terminal.html")
check("the archived terminal is still reachable", st == 200, str(st))

# ------------------------------------------------------------ injection

head("injection attempts in the filename")
evil = 'evil"; rm -rf / #.txt'
st, h, b = call("POST", "/versions/from-profile?name=" +
                urllib.request.quote(evil) + "&template=sheets")
st, h, raw = call("POST", f"/export/{b['id']}?format=txt", raw=True)
disp = h.get("content-disposition", "")
check("no CRLF in the disposition", "\r" not in disp and "\n" not in disp)
inner = disp.split("filename=", 1)[1].strip('"') if "filename=" in disp else disp
for ch in ('"', "/", "\\", ";", "#"):
    check(f"filename strips {ch!r}", ch not in inner, inner)
check("filename is not empty", bool(inner), inner)

# ------------------------------------------------------------------ done

head("summary")
print(f"  {CHECKS[0]} checks")
if FAILS:
    print(f"  {len(FAILS)} FAILED")
    for f in FAILS:
        print("   -", f)
    raise SystemExit(1)
print("  all green")