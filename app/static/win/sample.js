/* ============================================================================
   sample.js -- a finished resume to look at.

   Every employer, institution, date and number here is invented. "Sample
   Analytics" and "Sample Institute of Technology" do not exist, and the
   benchmarks are the kind of round figures a demo needs in order to be
   readable rather than flattering.

   It lives in its own file because it is content, not behaviour: the same data
   has to be reachable by the Sample Resume window, by the screenshot tooling,
   and by the tests, without any of them owning it.

   This was duplicated in the archived terminal at win/old-app.js, which carried
   its own frozen copy for tests to assert against. The archive has been deleted,
   so this file is now the only copy.
   ========================================================================= */

(function (global) {
'use strict';

/* Every field the model requires, so the API accepts this without repair. */
function buildSample() {
  return {
    contact: {
      name: 'Anon',
      email: 'anon@example.com',
      phone: '555-0100',
      city: '',
      country: '',
      links: [
        { label: 'Website', url: 'example.org' },
      ],
    },
    summary: '',
    // Obviously-not-a-real-person filler. The sheets template renders an
    // Interests line, and an empty string leaves that layout path untested --
    // but a real hobby list would be invented personal data.
    interests: 'Sample hobby one, sample hobby two',
    education: [{
      institution: 'Sample Institute of Technology',
      degree: 'B.E. Computer Science',
      field: 'Computer Science',
      start: '2019-08',
      end: '2022-06',
      grade: { value: '8.72', scale: '10' },
      coursework: ['Databases', 'Distributed Systems'],
    }],
    experience: [{
      org: 'Sample Analytics',
      role: 'Backend Engineer',
      type: 'job',
      location: '',
      start: '2022-07',
      end: 'Present',
      bullets: [
        { raw_facts: '900ms -> 240ms',
          text: 'Cut p99 checkout latency from 900ms to 240ms by adding Redis '
              + 'read-through caching on the payment-intent path.' },
        { raw_facts: '11 -> 15, 4 services, no downtime',
          text: 'Migrated Postgres 11 to 15 across 4 services using logical '
              + 'replication, with zero customer-visible downtime.' },
        { raw_facts: '5 -> 12 engineers',
          text: 'Mentored 5 engineers into owning the settlement service, '
              + 'growing that team to 12 without extra headcount.' },
      ],
    }],
    projects: [{
      name: 'Shift Scheduler',
      role: 'Solo build',
      links: [{ label: 'GitHub', url: 'example.org/scheduler' }],
      start: '2021-01',
      end: '2021-06',
      tech: ['FastAPI', 'PostgreSQL', 'Celery', 'Redis'],
      bullets: [
        { raw_facts: '12 stores, 4h -> 30s',
          text: 'Built a shift scheduler now used by 12 stores to publish '
              + 'weekly rosters in under 30 seconds, down from 4 hours.' },
      ],
    }],
    skills: [
      { name: 'Languages', items: ['Python', 'SQL', 'Go'] },
      { name: 'Backend', items: ['FastAPI', 'Django', 'Celery', 'Redis'] },
      { name: 'Data', items: ['PostgreSQL', 'Kafka', 'MongoDB'] },
    ],
    certifications: [{
      name: 'AWS Certified Solutions Architect - Associate',
      issuer: 'Amazon Web Services',
      date: '2024-03',
    }],
    achievements: [
      { name: 'Winner, Hackathon 2021 - 1st of 240 teams' },
    ],
    extracurriculars: [],
    publications: [],
  };
}

global.SampleResume = {
  build: buildSample,
  /* True when a profile has something in it, so "load the sample" can refuse to
     overwrite real work instead of silently destroying it. */
  isEmpty: function (profile) {
    if (!profile || !profile.contact) return true;
    const c = profile.contact;
    const contactFilled = !!(c.name || c.email || c.phone);
    const lists = ['education', 'experience', 'projects', 'skills',
                   'certifications', 'achievements', 'extracurriculars',
                   'publications'];
    const anyList = lists.some(function (k) {
      return Array.isArray(profile[k]) && profile[k].length > 0;
    });
    return !(contactFilled || anyList);
  },
};

})(window);