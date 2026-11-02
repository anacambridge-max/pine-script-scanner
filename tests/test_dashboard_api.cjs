const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');

require.extensions['.ts'] = (loaded, file) => {
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  loaded._compile(code, file);
};

function route(name) {
  const file = path.resolve('app/api', name, 'route.ts');
  const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  }).outputText;
  const loaded = new Module(file, module);
  loaded.filename = file;
  loaded.paths = Module._nodeModulePaths(path.dirname(file));
  loaded._compile(code, file);
  return loaded.exports;
}

test('confirmed alignment counts only timely directional clues and keeps NR patterns outside the count', () => {
  const {signalAlignment} = require('../app/lib/signal-alignment.ts');
  const signal = {
    symbol: 'DELHIVERY', signal_type: 'BUY', signal_state: 'CONFIRMED',
    signal_time: '2026-10-27T09:15:00+05:30',
    metadata: {
      full_result: {timestamp: '2026-10-27T09:15:00+05:30'},
      sector_rank_type: 'TOP 3 GAINER',
      movement_evidence: {
        confirmed_at: '2026-10-27T09:18:00+05:30', observed_at: '2026-10-27T09:17:00+05:30',
        oi: {label: 'LONG BUILDUP'},
        news: [{impact: 'POSITIVE', published_at: '2026-10-27T09:19:00+05:30', title: 'Later headline'}],
      },
    },
  };
  const premarket = [{symbol: 'DELHIVERY', movement_direction: 'UP WATCH', snapshot_time: '2026-10-27T09:07:00+05:30'}];
  const context = {daily_context: {nr7: true}, market_evidence: {opening: {
    status: 'READY', timestamp: '2026-10-27T09:15:00+05:30',
    open: 400, close: 404, move_pct: 4, gap_pct: 3, volume_multiple: 15,
    body_ratio: .4, close_location: .68,
  }}};
  const result = signalAlignment(signal, premarket, context);
  assert.equal(result.count, 4);
  assert.equal(result.labels.some(label => label.includes('News')), false);
  assert.equal(result.labels.some(label => label.includes('NR7')), false);
  assert.equal(signalAlignment({...signal, signal_type: 'SELL'}, premarket, context).count, 0);
  assert.equal(signalAlignment({...signal, metadata: {...signal.metadata, sector_rank_type: undefined, movement_evidence: undefined}}, premarket, context).count, 2);
});

test('NSE filing context respects event time and cannot become a directional confirmation clue', () => {
  const {latestFiling} = require('../app/lib/market-context.ts');
  const {signalAlignment} = require('../app/lib/signal-alignment.ts');
  const filings = [
    {title:'Quarterly results',url:'https://nsearchives.nseindia.com/corporate/a.pdf',published_at:'2026-10-30T16:07:00+05:30',source:'NSE filing',period:'PREVIOUS SESSION',impact:'MATERIAL EVENT / DIRECTION UNVERIFIED',category:'RESULTS'},
    {title:'Later result',url:'https://nsearchives.nseindia.com/corporate/b.pdf',published_at:'2026-11-02T10:00:00+05:30',source:'NSE filing',period:'SAME DAY',impact:'MATERIAL EVENT / DIRECTION UNVERIFIED',category:'RESULTS'},
  ];
  assert.equal(latestFiling(filings, '2026-11-02T09:15:00+05:30').title, 'Quarterly results');
  const signal = {symbol:'DIXON',signal_type:'BUY',signal_state:'CONFIRMED',signal_time:'2026-11-02T09:15:00+05:30'};
  const context = {market_evidence:{filings,opening:{status:'PENDING'}}};
  assert.equal(signalAlignment(signal, [], context).count, 0);
});

test('signal query keeps both IST bounds and confirmed 3m filters', async () => {
  const previous = global.fetch;
  const oldBase = process.env.SUPABASE_URL;
  const oldKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = 'https://database.example';
  process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  try {
    let query;
    global.fetch = async (url) => { query = new URL(url); return Response.json([]); };
    const response = await route('signals').GET(new Request('https://scanner.example/api/signals?limit=500'));
    assert.equal(response.status, 200);
    const today = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Kolkata'}).format(new Date());
    assert.equal(query.searchParams.get('and'), `(signal_time.gte.${today}T09:15:00+05:30,signal_time.lt.${today}T10:00:00+05:30)`);
    assert.equal(query.searchParams.get('signal_state'), 'eq.CONFIRMED');
    assert.equal(query.searchParams.get('metadata->>timeframe'), 'eq.3');
  } finally {
    global.fetch = previous;
    if (oldBase === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = oldBase;
    if (oldKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = oldKey;
  }
});

test('performance excludes untracked history and preserves ambiguous hits', async () => {
  const previous = global.fetch;
  const oldBase = process.env.SUPABASE_URL;
  const oldKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = 'https://database.example';
  process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  const outcome = (first_hit, value) => ({ score: 85, signal_time: '2026-10-12T09:18:00+05:30', metadata: { outcome: { version: 1, status: 'COMPLETE', first_hit, returns_pct: { '15': value, '30': value, '60': value } } } });
  try {
    global.fetch = async () => Response.json([outcome('TARGET', 1), outcome('STOP', -1), outcome('AMBIGUOUS', 0), { score: 99, signal_time: '2026-10-12T09:15:00+05:30', metadata: {} }]);
    const report = await (await route('performance').GET()).json();
    assert.equal(report.tracked, 3);
    assert.equal(report.complete, 3);
    assert.deepEqual(report.firstHit, { target: 1, stop: 1, ambiguous: 1, neither: 0 });
    assert.equal(report.medianReturnPct['60'], 0);
    assert.equal(report.sufficientSample, false);
  } finally {
    global.fetch = previous;
    if (oldBase === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = oldBase;
    if (oldKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = oldKey;
  }
});

test('health distinguishes current, stale, absent and unreachable worker', async () => {
  const previous = global.fetch;
  const oldBase = process.env.SUPABASE_URL;
  const oldKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = 'https://database.example';
  process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  try {
    const handler = route('health');
    for (const [rows, expected] of [
      [[{ status:'LIVE', last_run_at:new Date().toISOString() }], 'LIVE'],
      [[{ status:'STALE', last_run_at:new Date().toISOString() }], 'STALE'],
      [[{ status:'LIVE', last_run_at:new Date(Date.now()-120000).toISOString() }], 'OFFLINE'],
      [[], 'OFFLINE'],
      [[{status:'LIVE',last_run_at:'invalid'}], 'OFFLINE'],
    ]) {
      global.fetch = async () => Response.json(rows);
      assert.equal((await (await handler.GET()).json()).status, expected);
    }
    global.fetch = async () => { throw new Error('DNS unavailable'); };
    const response = await handler.GET();
    assert.equal(response.status, 503);
    assert.equal((await response.json()).status, 'UNAVAILABLE');
  } finally {
    global.fetch = previous;
    if (oldBase === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = oldBase;
    if (oldKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = oldKey;
  }
});


test('pre-market pagination uses offset and rejects unqualified raw symbols', async () => {
  const previous = global.fetch;
  const oldBase = process.env.SUPABASE_URL;
  const oldKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = 'https://database.example';
  process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  try {
    const offsets = [];
    global.fetch = async (url, options) => {
      const offset = Number(new URL(url).searchParams.get('offset'));
      offsets.push(offset);
      assert.equal(options.headers.Range, undefined);
      return Response.json(offset === 0
        ? Array.from({length: 1000}, (_, i) => ({symbol: 'S'+i, snapshot_time:'2026-10-12T03:38:00+00:00', preopen_score: i}))
        : [{symbol:'OLDER', snapshot_time:'2026-10-12T03:37:00+00:00', preopen_score:0}]);
    };
    const response = await route('pre-market-study').GET();
    assert.equal(response.status, 200);
    const payload = await response.json();
    assert.deepEqual(offsets, [0, 1000]);
    assert.equal(payload.source_symbol_count, 1000);
    assert.equal(payload.rows.length, 0);
    assert.equal(payload.snapshot_count, 2);
    assert.equal(payload.study_complete, false);
  } finally {
    global.fetch = previous;
    if (oldBase === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = oldBase;
    if (oldKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = oldKey;
  }
});

test('movement watch requires repeated aligned gap and liquid order pressure', () => {
  const { selectMovementCandidates } = require('../app/lib/premarket-selection.ts');
  const make = (symbol, minute, gap, buy, sell, extra = {}) => ({
    symbol, snapshot_time: `2026-10-12T03:${30 + minute}:00+00:00`, source_preopen: 'NSE',
    indicative_gap_pct: gap, indicative_price: 100, buy_qty: buy, sell_qty: sell, ...extra,
  });
  const rows = [
    make('UP', 5, 1.0, 10000, 3000), make('UP', 6, 1.1, 11000, 3000), make('UP', 7, 1.2, 12000, 3000),
    make('DOWN', 5, -1.1, 3000, 11000), make('DOWN', 6, -1.2, 3000, 11000), make('DOWN', 7, -1.3, 3000, 12000),
    make('THIN', 5, 1.2, 8, 2), make('THIN', 6, 1.2, 8, 2), make('THIN', 7, 1.2, 8, 2),
    make('FLIP', 5, -1.2, 3000, 11000), make('FLIP', 6, -1.2, 3000, 11000), make('FLIP', 7, 1.2, 11000, 3000),
    make('OI_ONLY', 5, 2, 10000, 3000, {source_preopen: null}),
    make('OI_ONLY', 6, 2, 10000, 3000, {source_preopen: null}),
    make('OI_ONLY', 7, 2, 10000, 3000, {source_preopen: null}),
  ];
  const selected = selectMovementCandidates(rows, '2026-10-12T03:37:00+00:00');
  assert.deepEqual(selected.map(row => row.symbol).sort(), ['DOWN', 'UP']);
  assert.equal(selected.find(row => row.symbol === 'UP').movement_direction, 'UP WATCH');
  assert.equal(selected.find(row => row.symbol === 'DOWN').movement_direction, 'DOWN WATCH');
  const largeGap = [make('LARGE', 5, 10, 16000, 6000), make('LARGE', 6, 10, 16000, 6000), make('LARGE', 7, 8.81, 16000, 6000)];
  assert.equal(selectMovementCandidates(largeGap, '2026-10-12T03:37:00+00:00')[0]?.symbol, 'LARGE');
});

test('sector support ranks gainers and losers separately and rejects stale context', () => {
  const { sectorSupport, isOpeningSignal } = require('../app/lib/market-context.ts');
  const now = new Date('2026-10-12T10:00:00+05:30');
  const context = {sector:'MEDIA', sector_change:-2, sector_gainer_rank:12, sector_loser_rank:1,
    sector_observed_at:'2026-10-12T09:59:00+05:30', sector_fresh:true};
  assert.equal(sectorSupport(context, 'SELL', now).bonus, 10);
  assert.equal(sectorSupport(context, 'BUY', now).bonus, 0);
  assert.equal(sectorSupport({...context, sector_observed_at:'2026-10-12T09:50:00+05:30'}, 'SELL', now).bonus, 0);
  assert.equal(sectorSupport({...context, sector_observed_at:'2026-10-09T09:59:00+05:30'}, 'SELL', now).bonus, 0);
  assert.equal(sectorSupport({...context, sector_change:3,sector_gainer_rank:1}, 'UP WATCH', now).bonus, 10);
  assert.equal(isOpeningSignal({full_result:{timestamp:'2026-10-12T09:15:00+05:30'}}, '2026-10-12T09:18:01+05:30'), true);
  assert.equal(isOpeningSignal({opening_candle:{is_opening:false}}, '2026-10-12T09:15:00+05:30'), false);
});

test('market context filters today and returns usable evidence shape', async () => {
  const previous = global.fetch;
  const oldBase = process.env.SUPABASE_URL;
  const oldKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  process.env.SUPABASE_URL = 'https://database.example';
  process.env.SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  try {
    global.fetch = async url => {
      const query = new URL(url);
      assert.equal(query.pathname, '/rest/v1/scanner_market_context');
      assert.equal(query.searchParams.get('trade_date'), 'eq.' + new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Kolkata'}).format(new Date()));
      return Response.json([{symbol:'TEST', daily_context:{nr7:true}, sector_context:{}, market_evidence:{}}]);
    };
    const response = await route('market-context').GET();
    assert.equal(response.status, 200);
    assert.equal((await response.json()).rows[0].daily_context.nr7, true);
    global.fetch = async () => new Response('unavailable', {status:503});
    assert.equal((await route('market-context').GET()).status, 503);
  } finally {
    global.fetch = previous;
    if (oldBase === undefined) delete process.env.SUPABASE_URL; else process.env.SUPABASE_URL = oldBase;
    if (oldKey === undefined) delete process.env.SUPABASE_SERVICE_ROLE_KEY; else process.env.SUPABASE_SERVICE_ROLE_KEY = oldKey;
  }
});

test('opening shortlist rejects weak candles and links only aligned confirmations', () => {
  const {selectOpeningLeaders, marketBreadth, sectorRotation} = require('../app/lib/opening-dashboard.ts');
  const now = new Date('2026-11-02T09:18:00+05:30');
  const base = {symbol:'DEMO', observed_at:'2026-11-02T09:17:00+05:30', daily_context:{status:'READY',compression:true},
    sector_context:{sector:'NIFTY AUTO',sector_change:1.8,sector_gainer_rank:1,sector_observed_at:'2026-11-02T09:17:00+05:30',sector_fresh:true},
    market_evidence:{opening:{status:'READY',timestamp:'2026-11-02T09:15:00+05:30',open:101,close:102,volume_multiple:12,gap_pct:1,move_pct:2,body_ratio:.75,close_location:.9},candle:{status:'READY',change_pct:2},news:[]}};
  const rows = [base,{...base,symbol:'WEAK',market_evidence:{...base.market_evidence,opening:{...base.market_evidence.opening,body_ratio:.1},candle:{status:'READY',change_pct:-1}}}];
  const leaders = selectOpeningLeaders(rows,[{symbol:'DEMO',signal_type:'BUY',signal_state:'CONFIRMED'}],[],now);
  assert.deepEqual(leaders.map(row => row.symbol),['DEMO']);
  assert.equal(leaders[0].tier,'EXPLOSIVE');
  assert.equal(leaders[0].confirmed,true);
  assert.match(leaders[0].sectorLabel,/Sector Top Gainer/);
  assert.deepEqual(marketBreadth(rows,2,now),{advances:1,declines:1,unchanged:0,covered:2,universe:2,ratio:1,label:'PARTIAL COVERAGE'});
  assert.equal(sectorRotation(rows,now).length,1);
  assert.equal(selectOpeningLeaders(rows,[],[],new Date('2026-11-03T09:18:00+05:30')).length,0);
  const afterOpenNews = [{title:'Later announcement',published_at:'2026-11-02T10:00:00+05:30'}];
  const withLaterNews = [{...base,market_evidence:{...base.market_evidence,news:afterOpenNews}}];
  assert.equal(selectOpeningLeaders(withLaterNews,[],[],now)[0].reasons.includes('Fresh headline'),false);
  assert.equal(marketBreadth(rows,218,new Date('2026-11-02T09:25:00+05:30')).label,'QUOTES STALE');
});

test('gap-led opening watch keeps DELHIVERY-shaped extreme volume without treating it as a strong candle', () => {
  const {selectOpeningLeaders} = require('../app/lib/opening-dashboard.ts');
  const now = new Date('2026-11-02T09:20:00+05:30');
  const opening = {status:'READY',timestamp:'2026-11-02T09:15:00+05:30',open:400,close:402.85,
    gap_pct:3.63,move_pct:4.37,volume_multiple:34.7,body_ratio:.373,close_location:.693};
  const row = {symbol:'DELHIVERY',daily_context:{status:'READY',compression:false},sector_context:{},
    market_evidence:{opening,news:[]}};
  const signal = {symbol:'DELHIVERY',signal_type:'BUY',signal_state:'CONFIRMED'};
  const selected = selectOpeningLeaders([row],[signal],[],now);
  assert.equal(selected.length,1);
  assert.equal(selected[0].confirmed,true);
  assert.equal(selected[0].tier,'EXPLOSIVE');
  assert.ok(selected[0].reasons.includes('Gap-led opening volume'));
  assert.equal(selectOpeningLeaders([{...row,market_evidence:{opening:{...opening,close_location:.6},news:[]}}],[signal],[],now).length,0);
  assert.equal(selectOpeningLeaders([{...row,market_evidence:{opening:{...opening,volume_multiple:4},news:[]}}],[signal],[],now).length,0);
});

test('confirmed movement tags require full daily boundary and never use later OI/news', () => {
  const {confirmedPatternHint} = require('../app/lib/market-context.ts');
  const signal = {signal_state:'CONFIRMED',signal_type:'BUY',entry:105,rvol:3,metadata:{daily_context:{status:'READY',nr7:true,nr4:true,compression:true,pdh:104,pdl:99,trend:'DOWNTREND'},full_result:{body_ratio:.8,close_location:.9}}};
  assert.equal(confirmedPatternHint(signal).label,'Potential Top Gainer');
  assert.equal(confirmedPatternHint({...signal,entry:103}).label,null);
  assert.equal(confirmedPatternHint({...signal,signal_state:'WATCH'}).label,null);
  assert.equal(confirmedPatternHint({...signal,metadata:{...signal.metadata,full_result:{body_ratio:1.2,close_location:.9}}}).label,null);
  const evidence={confirmed_at:'2026-10-12T09:18:00+05:30',observed_at:'2026-10-12T15:30:00+05:30',oi:{label:'SHORT COVERING'},news:[{published_at:'2026-10-12T12:00:00+05:30',impact:'BULLISH MENTION',title:'later news'}]};
  assert.deepEqual(confirmedPatternHint({...signal,metadata:{...signal.metadata,movement_evidence:evidence}}).supporting,[]);
  evidence.observed_at='2026-10-12T09:17:00+05:30';
  assert.deepEqual(confirmedPatternHint({...signal,metadata:{...signal.metadata,movement_evidence:evidence}}).supporting,['SHORT COVERING']);
  assert.equal(confirmedPatternHint({...signal,signal_type:'SELL',entry:98}).label,'Potential Top Loser');
});

test('pattern filters actually narrow confirmed stocks and require combined candle strength', () => {
  const {matchesPatternFilter} = require('../app/lib/market-context.ts');
  const daily={status:'READY',compression:true,nr7:true,nr4:true,narrow_pd:false,pdh:104,pdl:99,trend:'DOWNTREND'};
  const signal={signal_state:'CONFIRMED',signal_type:'BUY',entry:105,rvol:3.2,metadata:{daily_context:daily,full_result:{body_ratio:.8,close_location:.9}}};
  for (const mode of ['STRONG','MOVERS','GAINERS','NR7','NR4']) assert.equal(matchesPatternFilter(signal,undefined,mode),true);
  for (const mode of ['LOSERS','NARROW','SUPPORTED']) assert.equal(matchesPatternFilter(signal,undefined,mode),false);
  assert.equal(matchesPatternFilter({...signal,rvol:2.5},undefined,'STRONG'),false);
  assert.equal(matchesPatternFilter({...signal,entry:103},undefined,'MOVERS'),false);
  assert.equal(matchesPatternFilter({...signal,signal_state:'WATCH'},undefined,'NR7'),false);
  assert.equal(matchesPatternFilter({...signal,signal_type:'SELL',entry:98},undefined,'LOSERS'),true);
  assert.equal(matchesPatternFilter({...signal,metadata:{}},undefined,'STRONG'),false);
});

test('common stocks require confirmation plus any one distinct other heading', () => {
  const {buildCommonStockRows} = require('../app/lib/cross-section.ts');
  const rows=buildCommonStockRows([{symbol:'SUZLON',signal_state:'CONFIRMED'},{symbol:'IRFC',signal_state:'CONFIRMED'},{symbol:'ALONE',signal_state:'CONFIRMED'},{symbol:'WATCH',signal_state:'WATCH'}],[{name:'PRE-MARKET WATCH',symbols:[' suzlon ','SUZLON','WATCH']},{name:'ALIGNED CONFIRMED',symbols:['SUZLON']},{name:'TECHNICAL ONLY',symbols:['IRFC','WATCH']}]);
  assert.deepEqual(rows.map(row => [row.symbol,row.count]),[['SUZLON',3],['IRFC',2]]);
  assert.deepEqual(rows[0].sections,['CONFIRMED SIGNALS','PRE-MARKET WATCH','ALIGNED CONFIRMED']);
  assert.deepEqual(buildCommonStockRows([{symbol:'ALONE',signal_state:'CONFIRMED'}],[]),[]);
});

test('trade selection uses candle/risk rules rather than stored scores or extreme volume', () => {
  const {selectionRules, compareSelections} = require('../app/lib/trade-selection.ts');
  const candidate = (symbol, score, body, location, rvol, stop) => ({symbol, score, signal_type:'BUY', signal_state:'CONFIRMED', entry:100, stop_loss:stop, rvol, metadata:{full_result:{body_ratio:body,close_location:location}}});
  const good = candidate('GOOD',20,.8,.9,4,99);
  const weak = candidate('WEAK',99,.3,.55,30,95);
  const rows=[weak,good].map(signal=>({signal,...selectionRules(signal)})).sort(compareSelections);
  assert.equal(rows[0].signal.symbol,'GOOD');
  assert.equal(rows[0].tier,'CLEAN SETUP');
  assert.equal(selectionRules(candidate('INVALID',100,.8,.9,5,101)).tier,'REVIEW SETUP');
  assert.equal(selectionRules(candidate('MISSING',100,undefined,undefined,5,99)).priority[0],-1);
});
