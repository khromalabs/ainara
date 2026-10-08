const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.slice(html.indexOf('<script>') + 8, html.lastIndexOf('</script>'));
// whole script must at least parse
new Function(script);
const eng = script.slice(script.indexOf('//<<ENGINE'), script.indexOf('//ENGINE>>'));
const api = new Function(eng + '; return { EVENTS, HISTORY, LESSONS, COURSE_ORDER, COURSE_META, runQuery, compare, dedup, simMark, simRun, fullQuery, OPS_START, FIGS, HOWTO, howFind, stepsFig, searchAll, CLEAN_START, LAB_SEED, LAB_PUBLIC, labMissions, labRun };')();
let bad = 0; const idx = {};
for (const c of api.COURSE_ORDER) {
  idx[c] = api.LESSONS[c].map((L) => ({ id: L.id, title: (L.project && !/^project/i.test(L.title) ? 'Project: ' : '') + L.title, project: !!L.project }));
  for (const L of api.LESSONS[c]) for (const T of (L.steps || [L.task, ...(L.more || [])])) {
    if (['rule', 'threshold', 'pair', 'pickrow', 'ops', 'cleanup', 'expire'].includes(T.type)) {
      let model, start;
      if (T.type === 'pickrow') { model = api.EVENTS.find((e) => e.Node === T.need.node && e.SubNode === T.need.sub).EventID; start = api.EVENTS[0].EventID; }
      else if (T.type === 'ops') { start = api.OPS_START(); model = api.OPS_START(); const r = model.find((e) => e.Node === T.need.node && e.SubNode === T.need.sub); r.Ack = 1; r.OwnerName = 'you'; r.Journal = 'x'; }
      else if (T.type === 'cleanup') { start = api.CLEAN_START(); model = api.CLEAN_START().filter((r) => !r.Summary.startsWith('TRAIN_TEST')); if (api.simMark(T, api.CLEAN_START().slice(1)).msg.indexOf('real alarm') < 0) { bad++; console.log('BAD cleanup: deleting a real alarm not caught'); } }
      else { model = T.need; start = T.start; }
      const m = api.simMark(T, model), s0 = api.simMark(T, start);
      const flag = m.correct && !s0.correct && s0.msg ? 'ok' : 'BAD'; if (flag === 'BAD') bad++;
      console.log(flag, L.id, T.type, 'rows', T.type === 'pickrow' ? '-' : api.simRun(T, model).length, 'start->', (s0.msg || 'ALREADY RIGHT').slice(0, 100));
      continue;
    }
    if (['sql', 'kql', 'es'].includes(T.type)) {
      const m = api.runQuery(T.type, api.fullQuery(T, T.answer));
      const self = api.compare(T.type, m, m);
      const start = T.start ? api.compare(T.type, api.runQuery(T.type, api.fullQuery(T, T.start)), m) : { correct: false };
      const flag = (!m.ok || !self.correct || start.correct || (!m.aggs && (m.total === 0 || m.total === m.of) && L.id !== 'ea4')) ? 'BAD' : 'ok';
      if (flag === 'BAD') bad++;
      console.log(flag, L.id, T.type, 'total', m.total, 'of', m.of, m.ok ? '' : m.error, m.aggs ? JSON.stringify(Object.values(m.aggs)[0]) : '', 'start->', start.correct ? 'ALREADY RIGHT' : (start.msg || '').slice(0, 90));
    } else console.log('ok', L.id, T.type);
  }
}
const t = (lang, q) => { const r = api.runQuery(lang, q); return r.ok ? r.total + (r.aggs ? ' aggs' : '') + (r.cat ? ' cat' : '') : 'ERR ' + r.error.split('\n')[0]; };
const cases = [
 ['sql', ''], ['sql', "severity=5 and ack=0"], ['sql', "WHERE Severity = 5 AND Node LIKE 'TST1%' OR Node LIKE 'RAN1%'"], ['sql', "SubMethod IN ('SRC_A','SRC_B') AND Count > 10"],
 ['sql', "Severity >= 4 AND TicketID = ''"], ['sql', "NOT (Severity < 4) AND Node NOT LIKE 'RAN%'"], ['sql', "FirstReported > (UNIX_TIMESTAMP() - 3600) * 1"], ['sql', "Count BETWEEN 5 AND 15"],
 ['sql', "Nod = 'x'"], ['sql', "Severity = "], ['sql', "select * from Events"], ['sql', "Summary LIKE '%loss of signal%'"], ['sql', "(Severity = 5)"], ['sql', "TicketID IS NOT NULL AND TicketID != ''"],
 ['kql', ''], ['kql', 'Node : RAN1_*'], ['kql', 'Severity.name : critical'], ['kql', 'Severity >= 4 and not Ack : 1'], ['kql', 'SubMethod : ("SRC_A" or "SRC_B")'], ['kql', 'Summary : "loss of signal"'], ['kql', 'Summary : signal'],
 ['kql', 'Node : RAN1_001 Severity : 5'], ['kql', 'Foo : 1'], ['kql', 'RAN1_003'], ['kql', 'Severity : 5 and (Node : TST1_* or Node : TX1_*)'], ['kql', '@timestamp >= now-1h'],
 ['es', 'GET _cat/indices/eventanalytics-*?v'], ['es', 'DELETE eventanalytics-*'], ['es', '{ "query": { "match_all": {} } }'], ['es', 'GET eventanalytics-*/_search\n{ "query": { "match": { "Node": "RAN1_001" } }, "sort": [ { "@timestamp": "desc" } ] }'],
 ['es', 'GET eventanalytics-*/_search\n{ "size": 0, "aggs": { "x": { "terms": { "field": "Summary" } } } }'], ['es', 'GET eventanalytics-*/_search\n{ "size": 0, "aggs": { "x": { "terms": { "field": "Summary.keyword", "size": 3 } } } }'],
 ['es', 'GET eventanalytics-*/_search\n{ "query": { "match_all": {} } '], ['es', 'GET foo/_search'], ['es', 'POST eventanalytics-*/_doc\n{"a":1}'], ['es', 'GET eventanalytics-*/_search\n{ "query": { "term": { "Severity": 5 } } }'],
 ['es', 'GET eventanalytics-*/_search\n{ "query": { "bool": { "should": [ { "term": { "Node.keyword": "RAN1_001" } }, { "prefix": { "Node": "TX1" } } ], "must_not": { "term": { "Ack": 1 } } } } }'],
];
cases.forEach(([l, q]) => console.log(l.padEnd(3), JSON.stringify(q).slice(0, 80).padEnd(82), '=>', t(l, q)));
console.log('dedup', [['Node'], ['Node', 'SubNode', 'EventType'], ['Node', 'SubNode', 'EventType', 'Time'], []].map((p) => api.dedup(p).length).join(','));
if (process.argv[3]) fs.writeFileSync(process.argv[3], JSON.stringify(idx, null, 1));
for (const h of api.HOWTO) { const L = (api.LESSONS[h.lesson[0]] || []).find((x) => x.id === h.lesson[1]); if (!L || (h.fig && !api.FIGS[h.fig]) || !['safe', 'care', 'ask'].includes(h.risk) || h.steps.length < 3 || !api.stepsFig(h.steps).includes('<svg')) { bad++; console.log('BAD howto', h.id); } }
const asks = [['how do I edit a saved filter', 'edit-filter'], ['how do I remove unwanted alarms from the list', 'delete-alarms'], ['how can I hide noisy alarms from my view', 'hide-noise'], ['how do I make old alarms expire automatically', 'auto-expire'], ['how do I clean up leftover test alarms', 'delete-alarms'], ['how do I create a filter', 'create-filter'], ['how can I set up a new alarm', 'new-alarm'], ['why did my alarm disappear', 'alarm-disappeared'], ['how do I change the severity of an alarm', 'change-severity'], ['the list is flooding with duplicate rows', 'too-many-rows'], ['how do I make a cpu threshold alarm', 'threshold'], ['how do i share my filter with the ran team', 'share-filter'], ['which nodes had the most alarms last week', 'count-alarms'], ['an alarm will not clear', 'wont-clear'], ['how do I add a column to the display', 'create-display'], ['how do I bake a cake', null], ['what is the weather', null]];
asks.forEach(([q, want]) => { const got = api.howFind(q); if ((got ? got.id : null) !== want) { bad++; console.log('BAD howFind', JSON.stringify(q), '->', got && got.id, 'wanted', want); } });
[['EventKey', 'terms', 'EventKey'], ['threshold', 'lessons', 'Thresholds: an alarm from a measurement'], ['restriction filter', 'lessons', 'Filter groups and restriction filters'], ['share a filter', 'how', 'How do I share a filter with a team?'], ['kql', 'lessons', 'KQL: field : value']].forEach(([q, kind, want]) => { const r = api.searchAll(q), first = r[kind][0], got = first && (first.term || first.title || first.q); if (got !== want) { bad++; console.log('BAD search', q, kind, '->', got); } });
if (api.searchAll('zzzz').how.length + api.searchAll('zzzz').lessons.length + api.searchAll('').terms.length) { bad++; console.log('BAD search: junk matched'); }
{ const seed = api.LAB_SEED(), lab = { filters: seed.slice(), deleted: 0, read: {} }, n = (l) => api.labMissions(l).filter((m) => m.done).length;
  if (n(lab) !== 0 || !api.labRun(seed[1].clause).ok || api.labRun(seed[4].clause).ok) { bad++; console.log('BAD lab seed'); }
  lab.read.f2 = true; lab.filters.push({ id: 'u1', name: 'TRAIN_XX_Critical_Unack', owner: 'you', from: 'f2', clause: "Severity = 5 AND Ack = 0 AND Node LIKE 'RAN1%'" }, { id: 'u2', name: 'TRAIN_XX_Core', owner: 'you', from: 'f5', clause: "Severity >= 4 AND Node LIKE 'CORE1%'" }, { id: 'u3', name: 'TRAIN_XX_New', owner: 'you', clause: 'Count > 10' }); lab.deleted = 1;
  if (n(lab) !== 7) { bad++; console.log('BAD lab missions', JSON.stringify(api.labMissions(lab))); } }
console.log('howto topics', api.HOWTO.length);
if (process.argv[3]) fs.writeFileSync(require('path').join(require('path').dirname(process.argv[3]), 'howto.json'), JSON.stringify(api.HOWTO.map((h) => ({ id: h.id, q: h.q, keys: h.keys, where: h.where, risk: h.risk, steps: h.steps.map((s) => s[1]), note: h.note || '', lesson: h.lesson })), null, 1));
console.log(bad ? `${bad} BAD` : 'ALL LESSON ANSWERS OK');
