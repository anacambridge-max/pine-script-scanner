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
});
