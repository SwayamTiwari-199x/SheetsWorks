Turn the user's own words (plus their answers to interview questions) into structured resume entries. Output JSON only.

The input is free text. Extract:
- organization/company name (if present)
- role/title (if present)
- dates (if present; normalise to YYYY-MM or 'Present')
- bullets: array of strings — these are still rough/incomplete at this stage

DO NOT polish or add facts. Just structure what the user said. If a field is not mentioned, use an empty string. If dates are unclear, leave them empty.

OUTPUT FORMAT:
{"org": "...", "role": "...", "start": "...", "end": "...", "bullets": ["...", "..."]}

Example input: "at Google from 2021 to 2023 as a senior dev working on ads infra"
Example output:
{"org": "Google", "role": "Senior Dev", "start": "2021", "end": "2023", "bullets": ["working on ads infra"]}

Example input: "intern at a startup, built stuff with React and Node"
Example output:
{"org": "Startup", "role": "Intern", "start": "", "end": "", "bullets": ["built stuff with React and Node"]}
