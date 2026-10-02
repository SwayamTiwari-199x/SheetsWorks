# RULES.md — evidence-based resume conventions (Stage 0 output)

Every rule carries: source URL, date accessed, and a `verified`/`unverified` tag.
`verified` = corroborated by 2+ independent sources, or a primary source (study/government).
`unverified` = single secondary source, or plausible but not independently checked.

Date accessed for ALL sources: **2026-10-02**, unless noted.

This file is the origin of truth for ATS/layout/writing conventions in this app. "Refresh market data" task noted in §8.

---

## 0. Recruiter behavior

- Recruiters spend an average of **7.4 seconds** on an initial resume scan (Ladders eye-tracking study, 2018). —
  SOURCES: https://www.hrdive.com/news/eye-tracking-study-shows-recruiters-look-at-resumes-for-7-seconds/541582/ ; https://www.bu.edu/com/files/2018/10/TheLadders-EyeTracking-StudyC2.pdf ; https://www.theladders.com/career-advice/you-only-get-6-seconds-of-fame-make-it-count — **verified**
- Realistic range across studies and recruiter self-reports: **5–30 seconds** for the first pass. —
  SOURCE: https://standout-cv.com/usa/stats-usa/how-long-recruiters-spend-looking-at-resume — `unverified` (single secondary source, but consistent with the eye-tracking studies)
- Resumes that survive the scan have **simple layouts**; eye-tracking heatmaps show recruiters fixate first on: name, current title/company, dates, education (Ladders study). So contact + most-recent role + education must be scannable in seconds. —
  SOURCES: bu.edu and theladders.com above — **verified**
- Recruiters rarely run AI detectors, per limited evidence; ATS does not auto-reject on "AI-written" content; rejection risk is human (see §7). —
  SOURCE: https://www.reddit.com/r/jobsearchhacks/comments/1r32a25/i_spent_8_months_testing_how_ats_systems_actually/ (survey of 630 recruiters: 92% say their ATS does not auto-reject based on content) — `unverified` (forum-reported survey; no primary link) — but see §7 for the human side, which is well sourced.

## 1. Page limits by experience level

- Entry-level / fresher / student: **1 page**. —
  SOURCES: https://naukri.com/career-advice/how-to-make-resume-for-freshers ("should fit on one page", India) ; https://justcv.io/blogs/resume-examples-freshers/ ; https://ireformat.com/blog/ideal-resume-length-staffing ("Entry-level (0–5 yrs): one page") ; https://www.monster.com/career-advice/resume/how-long-should-a-resume-be (one to two pages depending on level) — **verified**
- Mid-career (~5–15 yrs): **1–2 pages**, 2 pages typical. —
  SOURCES: ireformat.com above; monster.com above — **verified**
- Senior/executive (15+ yrs): **2–3 pages** max. —
  SOURCE: https://ireformat.com/blog/ideal-resume-length-staffing ; monster.com above — `unverified`
- US federal (USAJOBS) resumes hard-capped at **2 pages** since Sept 27, 2025 (OPM Merit Hiring Plan). Relevant only for US government applications. —
  SOURCE: https://www.opm.gov/policy-data-oversight/hiring-information/merit-hiring-plan-resources/applicant-guidance-on-the-two-page-resume-limit/ — **verified** (primary)

## 2. ATS behavior

- Most "ATS rejection" is a myth in the strict sense: a 630-recruiter survey reports 92% say the ATS does not auto-reject by content; the ATS parses/ranks, humans decide. The real risk is **bad parsing** making the resume unreadable. —
  SOURCE: reddit jobsearchhacks thread above — `unverified`
- Modern ATS parse both text PDF and DOCX well; PDF is fine as long as it is **text-based** (not scanned image, not email-print-flattened). DOCX parses slightly more reliably; recruiters typically get/read PDFs. —
  SOURCES: https://www.resumefast.io/blog/ats-pdf-vs-word ; LinkedIn post https://www.linkedin.com/posts/sstruan_word-vs-pdf-r%C3%A9sum%C3%A9s-heres-what-really-activity-7323721323363360768-1Y5j ; https://resumey.pro/blog/ats-friendly-resume-fonts/ — **verified** (consensus)
- Parsing pitfalls (all corroborated): two-column layouts can scramble text order; tables/text boxes get dropped or reordered; graphics/icons/charts are lost; headers/footers may be missed (put contact info in body); decorative bullet glyphs can garble. —
  SOURCES: https://www.jobscan.co/blog/ats-formatting-mistakes/ ; https://www.resumly.ai/blog/formatting-resume-pdfs-best-practices-to-avoid-ats-errors ; https://recruitbpm.com/blog/resume-columns-and-ats-compatibility ; https://www.scu.edu/careercenter/toolkit/job-scan-common-ats-resume-formatting-mistakes/ — **verified**
  - Counterpoint: modern parsers handle two columns better than they used to — **single column remains the safest default**. SOURCE: https://enhancv.com/blog/ats-resume-parsing/ — **verified**
- **Safe fonts**: Calibri, Arial, Helvetica, Times New Roman, Cambria, Georgia, Verdana, Tahoma at 10.5–12pt body. —
  SOURCES: https://resumeoptimizerpro.com/blog/best-resume-fonts ; https://atsverification.com/blog/best-fonts-for-ats-resumes/ — **verified**
- Margins ≈1 inch; left-aligned text; consistent date formats (avoid `’21`; prefer `Jan 2024` or `2024-01` styles used consistently). —
  SOURCES: scu.edu and jobscan.co above — **verified**
- Reverse-chronological format scores best in major Indian parsers and generally. —
  SOURCES: https://www.naukri.com/career-advice/how-to-beat-applicant-tracking-systems ; https://www.naukri.com/career-advice/ats-meaning-what-it-is-for-your-resume — **verified**

## 3. Section order and headings

Safe headings (parsed correctly by common ATS): **Summary, Work Experience, Education, Skills, Technical Skills, Projects, Certifications**. Avoid creative titles ("My Journey", "What I Bring"). —
SOURCES: https://resumeatlas.io/resume-sections ; https://resumeoptimizerpro.com/blog/how-to-format-resume-for-ats ; https://www.indeed.com/career-advice/resumes-cover-letters/sections-of-a-resume — **verified**

Section order:

- **Experienced (tech):** Contact → Summary → Work Experience → Projects (if strong) → Skills → Education → Certifications.
- **Student/fresher (tech):** Contact → Summary → Education → Projects → Internships/Experience → Skills → Certifications → Achievements/Awards. Freshers lead with education + projects because projects and internships are the experience section. —
  SOURCES: https://justcv.io/blogs/resume-examples-freshers/ ; https://www.resumefast.io/blog/fresher-resume-guide ; https://resources.instahyre.com/blog/how-to-list-projects-on-resume/ ; https://hexerhire.in/blog/entry-level-software-engineer-resume-2026-ats-project-guide — **verified**
- General ATS-expected sequence: contact → summary → key skills → work experience → education → certifications. —
  SOURCE: https://jd2cv.uk/blog/resume-sections-order-ats-expects — `unverified`

Open-source contributions can be listed under Projects or a separate "Open Source" section for tech roles; when substantial, "Experience" is defensible. —
SOURCES: https://www.reddit.com/r/developersIndia/comments/1qg5aax/open_source_contributions_on_resume_experience_or/ ; https://www.quora.com/If-I-contribute-to-an-open-source-project-as-a-fresher-can-I-add-it-to-my-resume — `unverified`

## 4. Bullet writing rules

- **Structure:** action verb + what you did + how (tool/method) + measurable result. Google recruiter-endorsed X-Y-Z formula: "Accomplished [X] as measured by [Y] by doing [Z]". —
  SOURCES: https://www.inc.com/bill-murphy-jr/google-recruiters-say-these-5-resume-tips-including-x-y-z-formula-will-improve-your-odds-of-getting-hired-at-google.html ; https://careerservices.cns.utexas.edu/resources/resumes/resume-content ; https://www.kraftcv.com/blog/developer-guide-quantifying-impact-50-examples — **verified**
- **Length:** 1–2 lines max, ~15–30 words. If it wraps to a third line, split or trim. —
  SOURCES: https://www.extern.com/post/resume-bullet-points-guide ; https://airesume.guru/blog/resume-bullet-point-length-the-science-of-saying-more-with-less ; https://www.adobe.com/acrobat/resources/how-many-bullet-points-per-job-on-resume.html ; https://www.resumonk.com/articles/writing-resume-bullets — **verified**
- **Count per role:** ~3 bullets recent/important roles, fewer for older ones. —
  SOURCE: https://airesume.guru/blog/resume-bullet-point-length-the-science-of-saying-more-with-less — `unverified`
- **Varied verbs; no repeated opening word within a section; avoid "responsible for", "helped", "assisted in", "participated in", "duties included".** —
  SOURCES: https://www.indeed.com/career-advice/resumes-cover-letters/action-verbs-to-make-your-resume-stand-out ; https://www.jobscan.co/blog/powerful-verbs-that-will-make-your-resume-stand-out/ ; https://resumeoptimizerpro.com/blog/action-words-for-your-resume — **verified**
- **Tense:** present tense for current role, past tense for previous roles. —
  SOURCES: https://www.indeed.com/career-advice/resumes-cover-letters/should-current-job-be-in-present-tense-on-resume ; https://simplify.jobs/blog/resume-past-or-present-tense ; https://resume.io/blog/resume-tenses — **verified**
- **Summary:** 2–4 lines / 50–100 words; statement of who you are + top evidence, not an objective wish-list. —
  SOURCES: https://www.indeed.com/career-advice/resumes-cover-letters/writing-a-resume-summary-with-examples ; https://career.arizona.edu/resources/writing-a-resume-summary-statement/ ; https://aiapply.co/blog/resume-objective-vs-summary — **verified**

## 5. Banned / overused phrases

Flagged by recruiters as empty claims; do not generate these:
team player, hard worker / hardworking, detail-oriented, results-driven, results-oriented, self-starter, go-getter, passionate about, think outside the box, rockstar, ninja, guru, synergy, outside-the-box, "responsible for", "worked on various", "involved in", "excellent communication skills". —
SOURCES: https://resumeworded.com/resume-buzzwords-and-cliches-key-advice ; https://www.monster.com/career-advice/resume/resume-buzzwords ; https://www.resumerefiner.ai/blog/resume-buzzwords-to-avoid ; https://www.altis.com/learn/stop-using-these-10-overused-resume-phrases-and-what-to-write-instead ; https://zoomdraincareers.com/hiring/six-buzzwords-and-phrases-to-avoid-at-all-cost-when-building-your-resume/ — **verified**

## 6. Tech-role and fresher specifics

- Projects on tech resumes need: problem solved, tech stack, your specific role, result/metric, and a link. Links (GitHub/portfolio/project) must be live and clickable. Clean up the GitHub profile before pointing to it. —
  SOURCES: https://resources.instahyre.com/blog/how-to-list-projects-on-resume/ ; https://resumeworded.com/github-on-resume-key-advice ; https://mentorcruise.com/blog/why-your-software-engineering-resume-is-getting-ghosted-and-how-to-hack-the-process-e/ — **verified**
- Quantification patterns that work for engineers: scale (users, req/s, rows), performance/latency, cost, time saved, reliability, team size. When no number exists naturally, report the scale of work (e.g., "3-person team", "handled X collection of…") rather than inventing impact. —
  SOURCES: https://www.kraftcv.com/blog/developer-guide-quantifying-impact-50-examples ; inc.com XYZ above — **verified**
- Internships (incl. unpaid) go under Experience or a dedicated Internships heading; for freshers they ARE professional experience. Unpaid/coffee-fetching framing is not required; describe real work. —
  SOURCES: https://www.resumefast.io/blog/fresher-resume-guide ; https://justcv.io/blogs/resume-examples-freshers/ — `unverified`
- Coursework belongs on student resumes and is dropped by ~senior level; Class 10/12 marks are dropped once you have higher education. —
  SOURCES: https://www.indeed.com/career-advice/resumes-cover-letters/sections-of-a-resume ; https://www.naukri.com/career-advice/how-to-write-a-resume ("Drop your Class 10 and 12 marks now") — **verified**

## 7. AI-written resumes — honest note on detection and recruiter attitudes

Do NOT build detector evasion (per SPEC). The research justifies this:

- ~80% of hiring managers can spot an AI-written resume on sight (Resume Genius survey of 1,000 US hiring managers, 2025/26). —
  SOURCE: https://www.linkedin.com/posts/rachelwellscareerexpert_8-in-10-hiring-managers-spot-ai-resumes-activity-7440512939658244096-SLrN — `unverified` (survey reported secondhand; Forbes and Reddit coverage exists)
- 33.5% of hiring managers can identify AI-generated content within 20 seconds; **19.6% would reject an AI-generated resume outright** (TopResume survey of 600 US hiring managers, 2025). —
  SOURCES: https://topresume.com/career-advice/ai-in-hiring-survey ; https://www.jobsprout.ai/blog/can-employers-tell-if-you-used-ai-on-your-resume — **verified**
- 62% of employers in a 2025 Resume Now survey reject AI-generated resumes **that lack personalization**. —
  SOURCE: https://resumevera.com/blogs/can-recruiters-tell-chatgpt-resume — `unverified` (secondary retelling; aligns with TopResume)
- Recruiters are flooded with AI materials; the concern is authenticity/fraud, not AI per se — 59% have encountered AI-fabricated candidacy. —
  SOURCE: https://www.naceweb.org/career-readiness/best-practices/the-ghostwritten-candidate-ai-fraud-auto-apply-and-the-fight-for-authentic-career-readiness — `unverified`
- Counterpoint: a 2025 Journal of Applied Psychology study found AI-assisted resumes actually scored **higher** with hiring managers. Detection is unreliable; rejection is driven by generic/buzzword-laden tone and unverifiable claims. —
  SOURCE: https://careerbldr.com/blog/ai-resume-detection-hiring-managers/ — `unverified`
- **Therefore the app's position:** the defense is (a) the user's own specific facts, numbers, and vocabulary, and (b) human review of every bullet — both already in the SPEC. No detector-tricks, ever.

## 8. Job market snapshot (STALE — refresh regularly)

> **`refresh_market_data` task:** re-run this section's searches every ~3 months. Everything below was gathered 2026-10-02 and WILL go stale.

**India (2026):**
- In-demand: AI/ML, cloud, data science/analytics, cybersecurity, automation. —
  SOURCES: https://timesofindia.indiatimes.com/business/india-business/indian-it-sector-layoffs-which-jobs-are-facing-pressure-which-skills-are-in-demand/articleshow/134614885.cms ; https://www.scaler.com/blog/top-it-skills-in-demand/ ; https://wheebox.com/assets/pdf/ISR_Report_2026.pdf (India Skills Report 2026: 20% YoY rise in tech vacancies) — **verified**
- Demand for advanced digital skills up ~42% YoY (Taggd Decoding Jobs Report 2026, cited netmaxtech.com). Python, TensorFlow, PyTorch named. —
  SOURCE: https://netmaxtech.com/10-it-skills-india/ — `unverified`
- India Skills Report 2026: overall employability ~56.35%. — SOURCE: wheebox.com PDF above — **verified**

**Global (2026):**
- Software engineering listings up ~30% in 2026; roles requiring 2+ AI skills pay 43% more. New-grad big-tech hiring down vs 2019; senior/parallel roles up. —
  SOURCES: https://www.linkedin.com/posts/upstackhq_hiring-ai-activity-7456689813316923393-9PkV ; https://www.linkedin.com/news/story/software-engineering-jobs-prove-resilient-amid-ai-surge-8984258/ — `unverified` (LinkedIn-reported data, no primary report link)
- Most-listed AI-engineer skills: LangChain, RAG, PyTorch (LinkedIn report). —
  SOURCE: https://www.linkedin.com/posts/tariqalicreedtech_the-most-in-demand-job-in-2026-ai-engineer-activity-7503767553366929411-MEyy — `unverified`

## 9. India-specific rules (vs global)

- **Photos / DOB / gender / marital status / father's name:** common in older Indian biodata formats. Modern guidance (and all global/ATS contexts): **omit them**. Not expected for private-sector roles in India either; include only when a form asks (government/biodata contexts are separate documents entirely). —
  SOURCES: https://www.resumeaimatch.com/blog/india-resume-rules-guide ("Photo: not expected for most private-sector roles; avoid unless asked"; DOB "outdated") ; https://goodspace.ai/blogs/639310/personal-details-in-resume ("A generation ago, Indian resumes routinely opened with date of birth, father's name, marital status… That format is [outdated]") — **verified**
  - Counterpoint (legacy view): some older guides and even current generic Indian format guides (Kickresume, Monster, ResumeGenius) still mention photos/DOB as "common in India". Not endorsed here; treat as legacy. —
    SOURCES: https://www.kickresume.com/en/blog/indian-resume-format-guide/ ; https://www.monster.com/career-advice/resume/indian-resume-format — noted, **verified that they say this** (we treat it as outdated advice)
- **CGPA/percentage:** Indian freshers listing CGPA is normal and expected for campus placements and service companies; list 10th/12th marks only for campus/off-campus fresher drives that ask; drop them after first job or for experienced roles. We always include an explicit grade scale (e.g. "8.7/10") — parsers and global readers can't interpret a bare number. —
  SOURCES: https://www.naukri.com/career-advice/how-to-write-a-resume ; https://www.naukri.com/career-advice/resume-for-12th-pass-student ; https://resume-ai.in/fresher-resume-format — **verified** (India) / rule about scale: our design decision informed by the above + standard practice, `unverified` as an external claim.
- **Indian portals:** Naukri (and its RMS), LinkedIn, Foundit parse resumes before recruiters look; parser-safe formats see ~3x more callbacks per Naukri's own data; reverse-chronological ranks best with major Indian parsers. —
  SOURCES: https://www.naukri.com/career-advice/ats-friendly-cv ; https://www.naukri.com/career-advice/how-to-beat-applicant-tracking-systems — **verified** (source is the vendor itself; treat number with caution — noted)
- **One page for freshers holds in India** (campus norms reinforce it). — SOURCES: naukri.com/career-advice/how-to-make-resume-for-freshers ; justcv.io above — **verified**
- **Application tracker `source` field** should include Naukri / Instahyre / Wellfound etc. (not just global portals) — our design decision from the same sources. `unverified`
