/* ============================================================================
   editor-model.js -- the rules for editing a resume, with no DOM anywhere.

   Every operation here is a pure function over a plain profile object. That is
   the whole design: the GUI calls these, and the tests drive these directly
   under node. In Stage 3 this logic lived inside a terminal UI, which meant the
   only way to test a draft that silently failed to commit was to fake a whole
   terminal. Not doing that again.

   WHY THIS FILE IS CAREFUL
   Every bug found in Stage 3 was a *shape* bug, not a logic bug:

     - bullets written as plain strings instead of {id, raw_facts, text, ...},
       which the API rejects with a 422;
     - `summary` and `interests` written as {text: "..."} objects when the model
       declares them as plain strings, so a draft produced a value the renderer
       would print as [object Object];
     - `grade 8.7` producing {"grade": "8.7"} instead of {"value", "scale"};
     - `link` overwriting contact.link when the model wants contact.links[].

   Each of those is now a named, tested rule below rather than a thing that
   happens to work. If you add a field, add it to SECTIONS and a test will tell
   you what shape it is supposed to be.
   ========================================================================= */

(function (global) {
'use strict';

/* ------------------------------------------------------------------ specs */
/* The single description of every section: is it a list, what are its scalar
   fields, what appends, and what a one-line summary of it looks like. The GUI
   builds itself from this, so a field cannot exist in the form and be missing
   from the model, or vice versa. */

const BULLET = { id: '', raw_facts: '', text: '', metrics: [], tags: [], tools: [] };

/* `required` exists so validate() can name the missing field. The API enforces
   these with min_length and answers a blank one with a 422 and a JSON path,
   which tells the user nothing they can act on. Every field listed here has a
   min_length in models.py -- keep the two in step. */
const SECTIONS = {
  contact: {
    label: 'Contact', list: false, kind: 'contact',
    required: ['name', 'email', 'phone'],
    blurb: 'How you are reached. Name, email and phone are required.',
  },
  summary: {
    label: 'Summary', list: false, kind: 'text',
    blurb: 'Two or three lines. The sheets format leaves this out entirely.',
  },
  interests: {
    label: 'Interests', list: false, kind: 'text',
    blurb: 'One line, printed last by the sheets format.',
  },
  education: {
    label: 'Education', list: true, kind: 'entry',
    fields: ['institution', 'degree', 'field', 'start', 'end', 'notes'],
    required: ['institution', 'start'],
    grade: true,
    appenders: { coursework: 'string' },
    blurb: 'School, what you studied, when, and your grade if it is good.',
  },
  experience: {
    label: 'Experience', list: true, kind: 'entry',
    fields: ['org', 'role', 'type', 'location', 'start', 'end'],
    required: ['org', 'role', 'start'],
    appenders: { bullet: 'bullet' },
    blurb: 'Jobs and internships. Bullets carry the evidence.',
  },
  projects: {
    label: 'Projects', list: true, kind: 'entry',
    fields: ['name', 'role', 'start', 'end'],
    required: ['name'],
    appenders: { tech: 'string', bullet: 'bullet' },
    blurb: 'Things you built. A project with numbers beats a project without.',
  },
  skills: {
    label: 'Skills', list: true, kind: 'entry',
    fields: ['name'],
    required: ['name'],
    // SkillGroup is the one entry type with no id in models.py, and the model
    // forbids extra inputs -- so adding one produces a 422 on save. Every other
    // entry kind carries an id, hence the flag rather than a hardcoded exception.
    hasId: false,
    appenders: { item: 'string' },
    blurb: 'Group them. "Backend: Python, FastAPI" beats a flat list.',
  },
  certifications: {
    label: 'Certifications', list: true, kind: 'simple',
    fields: ['name', 'issuer', 'date', 'url', 'details'],
    blurb: 'Name and who issued it. The date helps.',
  },
  achievements: {
    label: 'Achievements', list: true, kind: 'simple',
    fields: ['name', 'issuer', 'date', 'url', 'details'],
    blurb: 'Awards, wins, things you were recognised for.',
  },
  extracurriculars: {
    label: 'Extracurriculars', list: true, kind: 'simple',
    fields: ['name', 'issuer', 'date', 'url', 'details'],
    blurb: 'Clubs, volunteering, sport at a level worth mentioning.',
  },
  publications: {
    label: 'Publications', list: true, kind: 'simple',
    fields: ['name', 'issuer', 'date', 'url', 'details'],
    blurb: 'Papers, articles, talks.',
  },
};

const ORDER = ['contact', 'summary', 'interests', 'education', 'experience',
               'projects', 'skills', 'certifications', 'achievements',
               'extracurriculars', 'publications'];

const EXPERIENCE_TYPES = ['job', 'internship', 'freelance'];

function spec(section) { return SECTIONS[section] || null; }
function isList(section) { const s = spec(section); return !!(s && s.list); }
function isText(section) { const s = spec(section); return !!(s && s.kind === 'text'); }

/* --------------------------------------------------------------- dates */
/* The server normalises dates in models.normalise_date. This is the same rule
   written again in JavaScript, and it exists for one reason: without it the
   field still reads "July 2026" after a save that stored "2026-07", so the user
   cannot see what was recorded, and a typo only surfaces as a 422 whose loc
   path ("body.experience.0.start") means nothing to the person looking at it.

   tests/check_static.py reads DATE_MONTHS out of this file and compares it to
   _MONTH_NAMES in app/models.py, so the two copies cannot quietly drift. */

const DATE_HELP = 'Write it as 2026-07, or as July 2026 / Jul 2026 / 07/2026 / '
  + '2026 / 2026-07-15. For an ongoing role write Present, Current, Now, '
  + 'Ongoing or Till date.';

const PRESENT = 'Present';

const PRESENT_WORDS = [
  'present', 'current', 'currently', 'now', 'ongoing', 'till date', 'to date',
  'presently', 'still', 'todate', 'till now', 'to present', 'till present',
  'still going', 'still working',
];

const DATE_MONTHS = {
  jan: 1, january: 1, feb: 2, february: 2, mar: 3, march: 3,
  apr: 4, april: 4, may: 5, jun: 6, june: 6, jul: 7, july: 7,
  aug: 8, august: 8, sep: 9, sept: 9, september: 9,
  oct: 10, october: 10, nov: 11, november: 11, dec: 12, december: 12,
};

/* Which fields are dates, per section. Kept next to the field lists so a new
   date field has to be declared once. */
const DATE_FIELDS = {
  education: ['start', 'end'],
  experience: ['start', 'end'],
  projects: ['start', 'end'],
  certifications: ['date'],
  achievements: ['date'],
  extracurriculars: ['date'],
  publications: ['date'],
};

function isDateField(section, field) {
  const f = DATE_FIELDS[section];
  return !!(f && f.indexOf(field) !== -1);
}

/* Returns the stored form, or throws with a message that says what to type.
   Never guesses: an unreadable value is an error, not a plausible date. */
function normaliseDate(value) {
  if (value === null || value === undefined) return null;
  const raw = String(value).trim();
  if (!raw) return null;
  const low = raw.toLowerCase().replace(/[ .]+$/, '');
  if (PRESENT_WORDS.indexOf(low) !== -1 || raw === PRESENT) return PRESENT;

  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(raw)) return raw;

  let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (m) {
    if (!realDay(+m[1], +m[2], +m[3])) throw new Error(badDate(raw));
    return raw;
  }

  m = /^([A-Za-z]{3,9})\.?,?\s*[-/ ]?\s*(\d{4})\.?$/.exec(raw);
  if (m) return fromMonthName(m[1], m[2], raw);

  m = /^(\d{4})\s*[-/. ]\s*(\d{1,2})$/.exec(raw);
  if (m) return fromMonthName(null, m[1], raw, +m[2]);

  m = /^(?:(\d{1,2})(?:st|nd|rd|th)?\s*[-/.]\s*)?(\d{1,2})\s*[-/.]\s*(\d{4})$/.exec(raw);
  if (m) return fromMonthName(null, m[3], raw, +m[2], m[1] ? +m[1] : 0);

  m = /^(\d{4})\s*[-/. ]\s*([A-Za-z]{3,9})$/.exec(raw);
  if (m) return fromMonthName(m[2], m[1], raw);

  m = /^(\d{4})\.?$/.exec(raw);
  if (m) return m[1];   // a bare year stays a year, never January

  throw new Error(badDate(raw));
}

function badDate(raw) {
  return '\'' + raw + '\' is not a date I can read. ' + DATE_HELP;
}

function pad2(n) { return (n < 10 ? '0' : '') + n; }

function realDay(y, mo, d) {
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return false;
  const days = [31, (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0 ? 29 : 28,
    31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return d <= days[mo - 1];
}

/* Build YYYY-MM (or YYYY-MM-DD when a day was typed). `name` is null for the
   numeric forms. A day is only ever stored when the user typed one. */
function fromMonthName(name, year, raw, monthNumber, dayNumber) {
  let month = monthNumber;
  if (month === undefined) {
    month = DATE_MONTHS[String(name || '').toLowerCase().replace(/\.$/, '')];
  }
  if (!month || month < 1 || month > 12) throw new Error(badDate(raw));
  const y = Number(year);
  if (dayNumber) {
    if (!realDay(y, month, dayNumber)) throw new Error(badDate(raw));
    return String(y) + '-' + pad2(month) + '-' + pad2(dayNumber);
  }
  return String(y) + '-' + pad2(month);
}

/* --------------------------------------------------------------- helpers */

function uid(prefix) {
  return (prefix || 'id') + Math.random().toString(36).slice(2, 10);
}

function clone(value) {
  return value === undefined ? value : JSON.parse(JSON.stringify(value));
}

function entries(profile, section) {
  if (!profile) return [];
  const value = profile[section];
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

function count(profile, section) {
  if (isText(section) || section === 'contact') {
    const v = profile ? profile[section] : '';
    if (section === 'contact') {
      const c = (profile && profile.contact) || {};
      return (c.name || c.email || c.phone) ? 1 : 0;
    }
    return String(v || '').trim() ? 1 : 0;
  }
  return entries(profile, section).length;
}

function filled(profile) {
  return ORDER.filter((s) => count(profile, s) > 0);
}

function missing(profile) {
  return ORDER.filter((s) => count(profile, s) === 0);
}

/* -------------------------------------------------------------- bullets */

/* The single most important rule in this file. A bullet is an OBJECT with a
   text field, never a bare string. Stage 3 wrote strings, the API rejected
   them with a 422, and it took a test to notice. */
function makeBullet(text, rawFacts) {
  const t = String(text === undefined || text === null ? '' : text);
  return {
    id: uid('b'),
    raw_facts: rawFacts === undefined || rawFacts === null ? t : String(rawFacts),
    // raw_facts is the user's own words; text is the same until the AI polishes
    // it in a later stage. Nothing is invented here.
    text: t,
    metrics: [], tags: [], tools: [],
  };
}

function bulletText(b) {
  if (b && typeof b === 'object') return b.text || '';
  return String(b === undefined || b === null ? '' : b);
}

/* Coerce anything already in the profile into the object shape. Data written by
   an older build, or hand-edited, may hold bare strings; a save would be
   rejected, so normalise on the way in rather than surprising the user with a
   422 they cannot act on. */
function normaliseBullets(entry) {
  if (!entry || !Array.isArray(entry.bullets)) return entry;
  entry.bullets = entry.bullets.map((b) =>
    (b && typeof b === 'object') ? Object.assign({}, BULLET, b) : makeBullet(b));
  return entry;
}

/* ---------------------------------------------------------------- writes */

/* Set one scalar field on one entry (or on a text section, or on contact).
   Returns a short human-readable confirmation, or throws with a message the form
   can show verbatim. Throwing rather than returning an error object keeps the
   call sites honest: a caller cannot forget to check. */
function setField(profile, section, index, field, value) {
  if (!profile) throw new Error('no profile loaded');
  const s = spec(section);
  if (!s) throw new Error('unknown section: ' + section);

  /* --- the two text sections are plain strings in the model. Stage 3 wrote
     {text: "..."} here and the API rejected the result. --- */
  if (s.kind === 'text') {
    if (index !== null && index !== undefined) {
      throw new Error(section + ' is a single value, not a list');
    }
    profile[section] = String(value === undefined || value === null ? '' : value);
    return section + ' updated';
  }

  if (section === 'contact') {
    if (index !== null && index !== undefined) {
      throw new Error('contact is a single value, not a list');
    }
    const c = profile.contact || (profile.contact = {});
    // A link is a {label, url} object appended to links[], never a scalar
    // `link` field, which the model forbids outright.
    if (field === 'link') {
      return addLink(c, value);
    }
    if (['name', 'email', 'phone', 'city', 'country'].indexOf(field) === -1) {
      throw new Error('unknown contact field: ' + field);
    }
    c[field] = String(value === undefined || value === null ? '' : value);
    return field + ' set';
  }

  const list = profile[section] || (profile[section] = []);
  /* ONE-BASED, like addEntry / removeEntry / moveEntry, and like the numbers the
     form shows. This was 0-based while everything else was 1-based, so editing
     entry 1 silently edited entry 2 -- the kind of bug that reads as "the form
     is a bit odd" and is invisible in the source. */
  const i = index === null || index === undefined ? 1 : Number(index);
  const entry = list[i - 1];
  if (!entry) {
    throw new Error('there is no ' + section + ' entry ' + i
      + ' (you have ' + list.length + ')');
  }

  normaliseBullets(entry);

  /* grade is {value, scale}; `grade 8.7` must not produce {"grade": "8.7"}. */
  if (field === 'grade' || field === 'scale') {
    entry.grade = entry.grade || { value: '', scale: '' };
    entry.grade[field === 'grade' ? 'value' : 'scale'] =
      String(value === undefined || value === null ? '' : value);
    return field + ' set';
  }

  /* Appenders accumulate rather than replace. */
  const appender = s.appenders && s.appenders[field];
  if (appender) {
    const text = String(value === undefined || value === null ? '' : value);
    if (!text) throw new Error('nothing to add');
    if (field === 'link') return addLink(entry, text);
    if (field === 'bullet') {
      const [body, facts] = splitBullet(text);
      entry.bullets.push(makeBullet(body, facts));
      return 'bullet added (' + entry.bullets.length + ' total)';
    }
    const target = APPENDER_TARGET[field];
    return pushItem(entry, target, text);
  }

  if (s.kind === 'simple' && s.fields.indexOf(field) === -1) {
    throw new Error('unknown field for ' + section + ': ' + field);
  }
  if (field === 'link') return setLink(entry, value);

  if (s.fields.indexOf(field) === -1) {
    throw new Error('unknown field for ' + section + ': ' + field);
  }
  if (isDateField(section, field)) {
    // Normalise on the way in, not on the server. The field then shows what was
    // actually recorded, and an unreadable value is reported here -- where the
    // user is looking at the box they typed it into -- instead of arriving later
    // as a 422 naming a JSON path.
    entry[field] = normaliseDate(value);
    return field + ' set to ' + (entry[field] === null ? 'blank' : entry[field]);
  }
  entry[field] = String(value === undefined || value === null ? '' : value);
  return field + ' set';
}

const APPENDER_TARGET = {
  coursework: 'coursework',
  tech: 'tech',
  item: 'items',
};

/* --------------------------------------------------------------- lists */
/* Skills items, project tech and coursework are real lists now: one item per
   row, editable and removable, instead of one text line that could only be
   appended to. The old behaviour made a typo permanent -- there was no way to
   correct "Pythno" without deleting the whole group and retyping it -- and it
   made a duplicate invisible, because "Python, Python" reads as one skill to
   nobody. */

const LIST_TARGET = APPENDER_TARGET;

function listOf(profile, section, index, field) {
  const s = spec(section);
  if (!s) throw new Error('unknown section: ' + section);
  const target = LIST_TARGET[field];
  if (!target) throw new Error(section + ' has no ' + field + ' list');
  if (index === null || index === undefined) {
    throw new Error(section + ' ' + field + ' belongs to one entry');
  }
  const entry = entries(profile, section)[Number(index) - 1];
  if (!entry) {
    throw new Error('there is no ' + section + ' entry ' + index
      + ' (you have ' + entries(profile, section).length + ')');
  }
  return entry[target] || (entry[target] = []);
}

/* Two items are the same item when they differ only in case or surrounding
   space. "Python" and "python" printed on the same line looks like a mistake to
   a reader and doubles the skill for an ATS, which counts tokens. */
function sameItem(a, b) {
  return String(a).trim().toLowerCase() === String(b).trim().toLowerCase();
}

function pushItem(entry, target, text) {
  const arr = entry[target] || (entry[target] = []);
  const value = String(text).trim();
  if (!value) throw new Error('nothing to add');
  if (arr.some((x) => sameItem(x, value))) {
    throw new Error('\'' + value + '\' is already in this list');
  }
  arr.push(value);
  return target.replace(/s$/, '') + ' added (' + arr.length + ' total)';
}

/* Replace one item in place. Refuses a value that collides with a *different*
   row, so an edit cannot silently produce the duplicate that adding rejects. */
function setItem(profile, section, index, field, itemIndex, value) {
  const arr = listOf(profile, section, index, field);
  const i = Number(itemIndex);
  if (!(i >= 1 && i <= arr.length)) {
    throw new Error('there is no item ' + itemIndex + ' in this list (you have '
      + arr.length + ')');
  }
  const next = String(value === undefined || value === null ? '' : value).trim();
  if (!next) throw new Error('an empty item would print as a gap, so remove it instead');
  if (arr.some((x, j) => j !== i - 1 && sameItem(x, next))) {
    throw new Error('\'' + next + '\' is already in this list');
  }
  arr[i - 1] = next;
  return field + ' ' + i + ' set to ' + next;
}

function removeItem(profile, section, index, field, itemIndex) {
  const arr = listOf(profile, section, index, field);
  const i = Number(itemIndex);
  if (!(i >= 1 && i <= arr.length)) {
    throw new Error('there is no item ' + itemIndex + ' in this list (you have '
      + arr.length + ')');
  }
  const gone = arr.splice(i - 1, 1)[0];
  return 'removed ' + gone + ' (' + arr.length + ' left)';
}

/* The one-line form the renderer prints, so the form can show the user exactly
   what will be exported: "Languages: Python, SQL, Go". */
function groupLabel(entry) {
  if (!entry) return '';
  const items = (entry.items || []).filter((x) => String(x).trim());
  return items.length ? entry.name + ': ' + items.join(', ') : (entry.name || '');
}

/* "did the thing | because of the thing" -> text and raw facts. The author's own
   words for raw_facts, so a later AI pass has something to work from. */
function splitBullet(input) {
  const parts = String(input).split('|');
  const body = (parts[0] || '').trim();
  const facts = parts.length > 1 ? parts.slice(1).join('|').trim() : body;
  return [body, facts];
}

/* `link` is accepted wherever the model has a links[] array: contact, projects,
   and anything that grows one later. It is a pseudo-field rather than a real
   one, because the model forbids extra keys -- writing a scalar `link` would be
   rejected by the API with a 422 the user cannot act on. */
function setLink(entry, value) {
  return addLink(entry, value);
}

/* Links take either a "Label url" string (so the one-field dialog still works)
   or a {label, url} pair (so a two-field dialog can edit one without guessing
   where the label ends -- a label is very often more than one word, and splitting
   on the first space used to turn "My GitHub" into "My" plus "GitHub url"). */
function splitLink(value) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return {
      label: String(value.label === undefined ? '' : value.label).trim(),
      url: String(value.url === undefined ? '' : value.url).trim(),
    };
  }
  const raw = Array.isArray(value) ? value.join(' ') : String(value || '');
  const cut = raw.indexOf(' ');
  return {
    label: (cut === -1 ? raw : raw.slice(0, cut)).trim(),
    url: (cut === -1 ? '' : raw.slice(cut + 1)).trim(),
  };
}

/* A URL is compared without its scheme, without a leading "www.", without case
   and without a trailing slash, because "github.com/me",
   "https://GitHub.com/me/" and "http://www.github.com/me" are the same
   destination and printing all three is a visible mistake on the page. */
function normaliseUrl(u) {
  return String(u).trim().toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/^www\./, '')
    .replace(/\/+$/, '');
}

function sameLink(a, b) {
  return normaliseUrl(a) === normaliseUrl(b);
}

function addLink(owner, value) {
  const { label, url } = splitLink(value);
  if (!label || !url) {
    throw new Error('a link needs a label and a url: link GitHub github.com/me');
  }
  const arr = owner.links || (owner.links = []);
  if (arr.some((l) => sameLink(l.url, url))) {
    throw new Error('\'' + url + '\' is already in this list');
  }
  arr.push({ label: label, url: url });
  return 'link added: ' + label;
}

/* Edit one link in place. Both halves are required, because models.Link has
   min_length=1 on each: a half-filled link is a 422 the user cannot see the
   cause of. */
function updateLink(owner, linkIndex, value) {
  const arr = owner.links || (owner.links = []);
  const i = Number(linkIndex);
  if (!(i >= 1 && i <= arr.length)) {
    throw new Error('there is no link ' + linkIndex + ' (you have ' + arr.length + ')');
  }
  const { label, url } = splitLink(value);
  if (!label || !url) {
    throw new Error('a link needs both a label and a url -- '
      + 'label GitHub, url github.com/me');
  }
  if (arr.some((l, j) => j !== i - 1 && sameLink(l.url, url))) {
    throw new Error('\'' + url + '\' is already in this list');
  }
  arr[i - 1] = { label: label, url: url };
  return 'link ' + i + ' set to ' + label;
}

function removeLink(owner, linkIndex) {
  const arr = owner.links || (owner.links = []);
  const i = Number(linkIndex);
  if (!(i >= 1 && i <= arr.length)) {
    throw new Error('there is no link ' + linkIndex + ' (you have ' + arr.length + ')');
  }
  const gone = arr.splice(i - 1, 1)[0];
  return 'removed ' + gone.label + ' (' + arr.length + ' left)';
}

/* Which object owns a links[] array: contact is the profile itself, everything
   else is an entry in a list. One lookup so the UI cannot get it wrong. */
function linkOwner(profile, section, index) {
  if (section === 'contact') {
    return profile.contact || (profile.contact = {});
  }
  const entry = entries(profile, section)[Number(index) - 1];
  if (!entry) throw new Error('there is no ' + section + ' entry ' + index);
  return entry;
}

/* ------------------------------------------------------------ entry edits */

function blankEntry(section) {
  const s = spec(section);
  if (!s) throw new Error('unknown section: ' + section);
  if (!s.list) throw new Error(section + ' is not a list section');
  const entry = s.hasId === false ? {} : { id: uid('e') };
  if (s.kind === 'simple') {
    entry.name = ''; entry.issuer = ''; entry.date = null;
    entry.url = ''; entry.details = '';
    return entry;
  }
  if (section === 'skills') { entry.name = ''; entry.items = []; return entry; }
  if (section === 'education') {
    entry.institution = ''; entry.degree = ''; entry.field = '';
    entry.start = ''; entry.end = null; entry.notes = '';
    return entry;
  }
  if (section === 'experience') {
    entry.org = ''; entry.role = ''; entry.type = 'job';
    entry.location = ''; entry.start = ''; entry.end = null;
    entry.bullets = [];
    return entry;
  }
  if (section === 'projects') {
    entry.name = ''; entry.role = ''; entry.start = null; entry.end = null;
    entry.links = []; entry.tech = []; entry.bullets = [];
    return entry;
  }
  throw new Error('no blank shape for ' + section);
}

function addEntry(profile, section, entry) {
  if (!isList(section)) throw new Error(section + ' is not a list section');
  const list = profile[section] || (profile[section] = []);
  const e = entry || blankEntry(section);
  list.push(normaliseBullets(e));
  return list.length;
}

function removeEntry(profile, section, index) {
  if (!isList(section)) throw new Error(section + ' is not a list section');
  const list = profile[section] || [];
  const i = Number(index);
  if (!Number.isInteger(i) || i < 1 || i > list.length) {
    throw new Error('there is no ' + section + ' entry ' + index
      + ' (you have ' + list.length + ')');
  }
  list.splice(i - 1, 1);
  return list.length;
}

/* 1-based, because that is what the form shows and what a person says. */
function moveEntry(profile, section, from, to) {
  if (!isList(section)) throw new Error(section + ' is not a list section');
  const list = profile[section] || [];
  const a = Number(from), b = Number(to);
  if (!Number.isInteger(a) || a < 1 || a > list.length) {
    throw new Error('there is no ' + section + ' entry ' + from);
  }
  if (!Number.isInteger(b) || b < 1 || b > list.length) {
    throw new Error('cannot move to ' + to + '; there are ' + list.length + ' entries');
  }
  if (a === b) throw new Error('it is already at ' + a);
  /* Remove, then insert -- in that order, at the target's index in the SHORTER
     list. The first version computed the insert position against the
     pre-removal numbering and quietly produced [First, Third, Second] when
     asked for [Third, First, Second]. */
  const moved = list.splice(a - 1, 1)[0];
  list.splice(b - 1, 0, moved);
  return list;
}

/* ------------------------------------------------------------ validation */
/* Deliberately few rules, and each one earns its place by blocking a save the
   server would reject anyway -- so the user is told here rather than as a 422. */

function validate(profile) {
  const problems = [];

  /* Required fields, named. The API would reject these with a 422 and a JSON
     path like body.projects.0.name; this says which entry is missing what, in a
     sentence a person can act on. */
  for (const section of ORDER) {
    const s = SECTIONS[section];
    if (!s.required || !s.required.length) continue;
    if (section === 'contact') {
      const c = (profile && profile.contact) || {};
      s.required.forEach((field) => {
        if (!String(c[field] || '').trim()) {
          problems.push({ where: 'contact', message: 'Contact needs a ' + field + '.' });
        }
      });
      continue;
    }
    entries(profile, section).forEach((entry, i) => {
      s.required.forEach((field) => {
        const v = entry ? entry[field] : '';
        if (!String(v === undefined || v === null ? '' : v).trim()) {
          problems.push({
            where: section + ' ' + (i + 1),
            message: s.label + ' ' + (i + 1) + ' needs a ' + field + '.',
          });
        }
      });
    });
  }

  const c = (profile && profile.contact) || {};
  if (c.email && String(c.email).indexOf('@') === -1) {
    problems.push({ where: 'contact', message: 'That email has no @ in it.' });
  }

  /* Dates, checked here so the person is told which entry and which box, in a
     sentence, rather than receiving a 422 naming body.experience.2.end. The
     normalisation itself already happened in setField; this catches a value
     that arrived some other way (sample data, an older build, a paste). */
  Object.keys(DATE_FIELDS).forEach((section) => {
    if (!profile || !profile[section]) return;
    const list = entries(profile, section);
    list.forEach((entry, i) => {
      DATE_FIELDS[section].forEach((field) => {
        const v = entry ? entry[field] : null;
        if (v === null || v === undefined || String(v).trim() === '') return;
        try {
          normaliseDate(v);
        } catch (err) {
          problems.push({
            where: SECTIONS[section].label + ' ' + (i + 1),
            message: err.message,
          });
        }
      });
    });
  });

  (profile && profile.experience ? profile.experience : []).forEach((e, i) => {
    if (e.type && EXPERIENCE_TYPES.indexOf(e.type) === -1) {
      problems.push({
        where: 'Experience ' + (i + 1),
        message: 'Type must be one of: ' + EXPERIENCE_TYPES.join(', ') + '.',
      });
    }
    (e.bullets || []).forEach((b, j) => {
      if (!bulletText(b).trim()) {
        problems.push({
          where: 'Experience ' + (i + 1) + ' bullet ' + (j + 1),
          message: 'A bullet cannot be empty.',
        });
      }
    });
  });

  return problems;
}

/* ------------------------------------------------------------------ undo */

const MAX_UNDO = 60;

function History() {
  this.stack = [];
}

History.prototype.push = function (profile) {
  this.stack.push(JSON.stringify(profile));
  if (this.stack.length > MAX_UNDO) this.stack.shift();
};

History.prototype.canUndo = function () { return this.stack.length > 0; };

History.prototype.undo = function (profile) {
  if (!this.stack.length) throw new Error('nothing to undo');
  const previous = this.stack.pop();
  const restored = JSON.parse(previous);
  // Copy back rather than reassigning, so callers holding a reference to the
  // same object see the change.
  Object.keys(profile).forEach((k) => { delete profile[k]; });
  Object.keys(restored).forEach((k) => { profile[k] = restored[k]; });
  return profile;
};

/* ---------------------------------------------------------------- export */

global.EditorModel = {
  SECTIONS, ORDER, EXPERIENCE_TYPES, MAX_UNDO,
  DATE_FIELDS, PRESENT_WORDS, DATE_MONTHS, DATE_HELP,
  spec, isList, isText, entries, count, filled, missing,
  makeBullet, bulletText, normaliseBullets, splitBullet, blankEntry,
  setField, addEntry, removeEntry, moveEntry,
  setItem, removeItem, listOf, groupLabel, sameItem,
  addLink, updateLink, removeLink, linkOwner, splitLink, sameLink, normaliseUrl,
  normaliseDate, isDateField,
  validate, History, clone, uid,
};

})(typeof window !== 'undefined' ? window : globalThis);