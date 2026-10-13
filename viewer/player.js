'use strict';
const $ = id => document.getElementById(id);
const colors = ['#67c9a5', '#f48175', '#79aef2', '#d09cf2', '#f0bd65', '#6fd2df', '#ed94be', '#a8c66e'];
const size = 32, maxBytes = 512 * 1024 * 1024, maxFrames = 25000;
let data = null, last = 0, turn = 0, timer = null, loadGeneration = 0, selected = null;
let camera = {x: 0, y: 0, zoom: 1}, drag = null;

// Validate the fields this player consumes before changing the current match.
// Full deterministic rules verification remains the Rust verifier's job.
function validateReplay(d) {
  const fail = (p, why) => { throw new Error(`${p}: ${why}`); };
  const object = (v, p) => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) fail(p, '应为对象');
    return v;
  };
  const array = (v, p, length = null, max = Infinity) => {
    if (!Array.isArray(v) || (length !== null && v.length !== length) || v.length > max) fail(p, '数组长度或类型错误');
    return v;
  };
  const int = (v, lo, hi, p) => {
    if (!Number.isSafeInteger(v) || v < lo || v > hi) fail(p, '整数超出范围');
    return v;
  };
  const text = (v, p) => { if (typeof v !== 'string' || !v.length) fail(p, '应为非空文本'); };
  const id = (v, p) => v === null ? null : int(v, 1, Number.MAX_SAFE_INTEGER, p);
  object(d, 'replay');
  if (d.bundle_format !== 'fff-replay' || d.bundle_version !== 1) fail('replay', '需要版本 1 的 replay.json；请用 viewer/export.py 导出比赛目录，不能直接载入 manifest.json');
  const m = object(d.map, 'map'), manifest = object(d.manifest, 'manifest');
  int(m.format_version, 1, 1, 'map.format_version');
  int(manifest.format_version, 1, 1, 'manifest.format_version');
  const width = int(m.width, 9, 128, 'map.width'), height = int(m.height, 9, 128, 'map.height');
  const players = int(m.players, 2, 8, 'map.players');
  text(m.id, 'map.id'); text(manifest.match_id, 'manifest.match_id');
  if (!['complete', 'in_progress'].includes(manifest.status)) fail('manifest.status', '未知状态');
  if (typeof manifest.seed !== 'string' || !/^\d+$/.test(manifest.seed) || BigInt(manifest.seed) > 18446744073709551615n) fail('manifest.seed', '应为 64 位整数的十进制字符串');
  const limits = object(m.match_limits, 'map.match_limits');
  int(limits.target_score, 1, 4294967295, 'map.match_limits.target_score');
  int(limits.max_turns, 1, 1000000, 'map.match_limits.max_turns');
  const n = int(manifest.last_complete_turn, 0, Math.min(maxFrames, limits.max_turns), 'manifest.last_complete_turn');
  array(manifest.teams, 'manifest.teams', players).forEach((t, i) => {
    object(t, `manifest.teams[${i}]`); int(t.team_id, i, i, `manifest.teams[${i}].team_id`); text(t.name, `manifest.teams[${i}].name`);
  });
  array(m.terrain, 'map.terrain', height).forEach((row, y) => {
    if (typeof row !== 'string' || row.length !== width || /[^.#]/.test(row)) fail(`map.terrain[${y}]`, '地图格或宽度错误');
    if ((y === 0 || y === height - 1) && /\./.test(row) || row[0] !== '#' || row[width - 1] !== '#') fail('map.terrain', '地图边界未封闭');
  });
  const point = (v, p, bounded = false, floor = false) => {
    object(v, p); int(v.x, -2147483648, 2147483647, p + '.x'); int(v.y, -2147483648, 2147483647, p + '.y');
    if ((bounded || floor) && (v.x < 0 || v.x >= width || v.y < 0 || v.y >= height)) fail(p, '坐标超出地图');
    if (floor && m.terrain[v.y][v.x] !== '.') fail(p, '坐标位于障碍');
    return `${v.x},${v.y}`;
  };
  const uid = (v, p) => {
    object(v, p); int(v.team_id, 0, players - 1, p + '.team_id'); int(v.unit_id, 0, 2, p + '.unit_id');
    return v.team_id * 3 + v.unit_id;
  };
  const homes = new Set(), homeCells = new Set();
  array(m.spawn_regions, 'map.spawn_regions', players).forEach((h, i) => {
    const p = `map.spawn_regions[${i}]`; object(h, p);
    int(h.team_id, 0, players - 1, p + '.team_id'); int(h.width, 3, 3, p + '.width'); int(h.height, 3, 3, p + '.height');
    point(h, p, true, true);
    if (homes.has(h.team_id)) fail(p, '重复队伍'); homes.add(h.team_id);
    for (let dy = 0; dy < 3; dy++) for (let dx = 0; dx < 3; dx++) {
      const cell = point({x: h.x + dx, y: h.y + dy}, p, true, true);
      if (homeCells.has(cell)) fail(p, '出生区重叠'); homeCells.add(cell);
    }
  });
  const sites = new Set(), siteCells = new Set();
  array(m.flag_points, 'map.flag_points', null, 32).forEach((s, i) => {
    const p = `map.flag_points[${i}]`; object(s, p); int(s.id, 0, 4294967295, p + '.id');
    const cell = point(s, p, true, true);
    if (sites.has(s.id) || siteCells.has(cell) || homeCells.has(cell)) fail(p, '旗点重复或与出生区重叠');
    sites.add(s.id); siteCells.add(cell);
  });
  if (!sites.size) fail('map.flag_points', '缺少旗点');
  const site = (v, p) => { if (!sites.has(v)) fail(p, '未知旗点'); };
  const state = (s, t, p) => {
    object(s, p); int(s.turn, t, t, p + '.turn');
    array(s.scores, p + '.scores', players).forEach(v => int(v, 0, 4294967295, p + '.scores'));
    const occupied = new Set();
    array(s.units, p + '.units', players * 3).forEach((u, i) => {
      const q = `${p}.units[${i}]`; object(u, q);
      if (uid(u.id, q + '.id') !== i) fail(q, '棋子编号顺序错误');
      int(u.hp, 0, 3, q + '.hp'); id(u.carrying, q + '.carrying');
      if (u.position === null) {
        if (u.hp !== 0 || u.carrying !== null) fail(q, '死亡状态错误');
        int(u.respawn_at_turn, 1, 4294967295, q + '.respawn_at_turn');
      } else {
        const cell = point(u.position, q + '.position', true, true);
        if (!u.hp || occupied.has(cell) || u.respawn_at_turn !== null) fail(q, '棋子占格状态错误');
        occupied.add(cell);
      }
    });
    const byId = new Map(), sources = new Set();
    array(s.flags, p + '.flags', null, sites.size).forEach((f, i) => {
      const q = `${p}.flags[${i}]`; object(f, q); id(f.id, q + '.id'); site(f.site_id, q + '.site_id');
      if (f.id === null || byId.has(f.id) || sources.has(f.site_id)) fail(q, '旗帜编号或来源重复');
      byId.set(f.id, f); sources.add(f.site_id); object(f.location, q + '.location');
      if (f.location.state === 'ground') point(f.location.position, q + '.location.position', true, true);
      else if (f.location.state === 'carried') {
        const u = s.units[uid(f.location.unit, q + '.location.unit')];
        if (!u.position || u.carrying !== f.id) fail(q, '携旗者不一致');
      } else fail(q + '.location.state', '未知旗帜状态');
    });
    s.units.forEach((u, i) => {
      if (u.carrying !== null) {
        const f = byId.get(u.carrying);
        if (!f || f.location.state !== 'carried' || uid(f.location.unit, p + '.flag.unit') !== i) fail(p + '.units', '携旗关联不一致');
      }
    });
    const seen = new Set();
    array(s.sites, p + '.sites', sites.size).forEach((v, i) => {
      const q = `${p}.sites[${i}]`; object(v, q); site(v.site_id, q + '.site_id');
      if (seen.has(v.site_id)) fail(q, '重复旗点'); seen.add(v.site_id);
      id(v.active_flag_id, q + '.active_flag_id');
      if (v.active_flag_id === null) {
        int(v.next_attempt_turn, Math.max(1, t), 4294967295, q + '.next_attempt_turn');
        if (sources.has(v.site_id)) fail(q, '已存在关联旗');
      } else if (byId.get(v.active_flag_id)?.site_id !== v.site_id || v.next_attempt_turn !== null) fail(q, '旗点来源关联错误');
    });
    if (s.outcome !== null) {
      object(s.outcome, p + '.outcome'); text(s.outcome.reason, p + '.outcome.reason');
      array(s.outcome.winners, p + '.outcome.winners', null, players).forEach(w => int(w, 0, players - 1, p + '.outcome.winners'));
      const winners = s.scores.flatMap((v, i) => v === Math.max(...s.scores) ? [i] : []);
      if (JSON.stringify(winners) !== JSON.stringify(s.outcome.winners)) fail(p + '.outcome', '获胜队伍与比分不一致');
    }
  };
  const event = (e, p) => {
    object(e, p); text(e.type, p + '.type'); text(e.phase, p + '.phase'); text(e.event_id, p + '.event_id');
    if (e.type === 'shot') {
      uid(e.shooter, p + '.shooter'); point(e.target, p + '.target');
      for (const key of ['from', 'blocked_by']) if (e[key] != null) point(e[key], p + '.' + key, true);
      if (e.hit_unit != null) uid(e.hit_unit, p + '.hit_unit'); text(e.validation, p + '.validation');
      if (!['hit', 'miss', 'blocked', 'not_executed'].includes(e.result)) fail(p + '.result', '未知射击结果');
      int(e.damage, 0, 1, p + '.damage');
    }
    if (['hp_change', 'death', 'move', 'carry_change', 'score', 'respawn', 'respawn_blocked', 'action_invalid'].includes(e.type)) uid(e.unit, p + '.unit');
    if (e.type === 'hp_change') { int(e.before, 0, 3, p + '.before'); int(e.after, 0, 3, p + '.after'); }
    if (e.type === 'death') int(e.respawn_at_turn, 1, 4294967295, p + '.respawn_at_turn');
    if (e.type === 'move') { for (const k of ['from', 'target']) if (e[k] != null) point(e[k], p + '.' + k); text(e.reason, p + '.reason'); text(e.result, p + '.result'); }
    if (e.type === 'carry_change') { id(e.before, p + '.before'); id(e.after, p + '.after'); text(e.reason, p + '.reason'); }
    if (e.type === 'score') { int(e.team_id, 0, players - 1, p + '.team_id'); int(e.before, 0, 4294967295, p + '.before'); int(e.after, 0, 4294967295, p + '.after'); }
    if (['flag_spawned', 'flag_spawn_failed', 'flag_respawn_scheduled'].includes(e.type)) site(e.site_id, p + '.site_id');
    if (e.type === 'flag_spawned') { id(e.flag_id, p + '.flag_id'); point(e.position, p + '.position', true, true); }
    if (e.type === 'flag_spawn_failed') uid(e.occupant, p + '.occupant');
    if (e.type === 'flag_respawn_scheduled') { int(e.delay, 1, 1000000, p + '.delay'); int(e.next_attempt_turn, 1, 4294967295, p + '.next_attempt_turn'); }
    if (e.type === 'respawn' && e.position != null) point(e.position, p + '.position', true, true);
  };
  state(d.initial, 0, 'initial');
  array(d.records, 'records', n).forEach((r, i) => {
    const p = `records[${i}]`, t = i + 1; object(r, p); object(r.frame, p + '.frame');
    int(r.format_version, 1, 1, p + '.format_version'); int(r.frame.turn, t, t, p + '.frame.turn');
    array(r.call_order, p + '.call_order', players).forEach((v, j) => int(v, j, j, p + '.call_order'));
    state(r.frame.start, t, p + '.frame.start'); state(r.frame.end, t, p + '.frame.end');
    array(r.frame.events, p + '.frame.events', null, 10000).forEach((e, j) => event(e, `${p}.frame.events[${j}]`));
    array(r.calls, p + '.calls', players).forEach((c, j) => {
      const q = `${p}.calls[${j}]`; object(c, q); int(c.team_id, j, j, q + '.team_id'); int(c.turn, t, t, q + '.turn');
      if (!['ok', 'timeout', 'crash', 'load_error', 'protocol_error', 'ai_error'].includes(c.status)) fail(q + '.status', '未知调用结果');
      int(c.elapsed_us, 0, Number.MAX_SAFE_INTEGER, q + '.elapsed_us'); int(c.init_elapsed_us, 0, Number.MAX_SAFE_INTEGER, q + '.init_elapsed_us');
      if (c.error != null) text(c.error, q + '.error');
    });
  });
  if (manifest.status === 'complete') {
    object(d.summary, 'summary');
    const end = n ? d.records[n - 1].frame.end : d.initial;
    if (d.summary.complete !== true || d.summary.turns !== n || JSON.stringify(d.summary.scores) !== JSON.stringify(end.scores)) fail('summary', '与结束局面不一致');
  }
  return d;
}

function svg(name, attrs = {}, content, parent = $('board')) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  if (content !== undefined) el.textContent = content;
  parent.append(el); return el;
}
function label(id) { return id ? String.fromCharCode(65 + id.team_id * 3 + id.unit_id) : '—'; }
function pos(p) { return p ? `(${p.x},${p.y})` : '—'; }
function flags(id) { return id == null ? '无旗' : `⚑${id}`; }
function currentRecord() { return turn ? data.records[turn - 1] : null; }
function currentState() { const r = currentRecord(); return r ? r.frame[$('phase').value] : data.initial; }
function unitText(u) { return `${label(u.id)} · ${pos(u.position)} · ` + (u.position ? `HP ${u.hp}/3 · ${flags(u.carrying)}` : `死亡 · 第 ${u.respawn_at_turn} 回合复活`); }
function eventText(e) {
  switch (e.type) {
    case 'shot': return `${label(e.shooter)} → ${pos(e.target)} · ${e.result === 'hit' ? `命中 ${label(e.hit_unit)}，伤害 ${e.damage}` : e.result === 'blocked' ? '障碍遮挡' : e.result === 'miss' ? '落空' : `未执行：${e.validation}`}`;
    case 'hp_change': return `${label(e.unit)} 血量 ${e.before} → ${e.after}`;
    case 'death': return `${label(e.unit)} 死亡，第 ${e.respawn_at_turn} 回合复活`;
    case 'move': return `${label(e.unit)} ${pos(e.from)} → ${pos(e.target)} · ${e.result === 'moved' ? '移动成功' : e.reason}`;
    case 'carry_change': return `${label(e.unit)} ${flags(e.before)} → ${flags(e.after)} · ${e.reason}`;
    case 'score': return `队伍 ${e.team_id} 得分 ${e.before} → ${e.after}`;
    case 'flag_spawned': return `旗点 ${e.site_id} 生成旗 ${e.flag_id} ${pos(e.position)}`;
    case 'flag_spawn_failed': return `旗点 ${e.site_id} 生成失败：${label(e.occupant)} 已携旗`;
    case 'flag_respawn_scheduled': return `旗点 ${e.site_id} 等待 ${e.delay} 回合，第 ${e.next_attempt_turn} 回合尝试`;
    case 'respawn': return `${label(e.unit)} 复活 ${pos(e.position)}`;
    case 'respawn_blocked': return `${label(e.unit)} 出生区已满，延后复活`;
    default: return e.type;
  }
}
function buildBoard() {
  $('board').replaceChildren();
  const terrain = svg('g');
  for (let y = 0; y < data.map.height; y++) for (let x = 0; x < data.map.width; x++) {
    svg('rect', {x: x * size, y: y * size, width: size, height: size, fill: data.map.terrain[y][x] === '#' ? '#344555' : '#15232e', stroke: '#233440', 'stroke-width': .7}, undefined, terrain);
  }
  for (const h of data.map.spawn_regions) {
    svg('rect', {x: h.x * size, y: h.y * size, width: h.width * size, height: h.height * size, fill: colors[h.team_id], opacity: .15, stroke: colors[h.team_id], 'stroke-width': 2}, undefined, terrain);
    svg('text', {x: (h.x + .15) * size, y: (h.y + .45) * size, fill: colors[h.team_id], 'font-size': 11}, `HOME ${h.team_id}`, terrain);
  }
  for (const name of ['sites', 'flags', 'shots', 'unit-layer', 'health-bars']) svg('g', {id: name + (name === 'sites' || name === 'flags' || name === 'shots' ? '-layer' : '')});
}
function updateCamera() {
  if (!data) return;
  const w = data.map.width * size, h = data.map.height * size;
  camera.x = Math.max(-w / 2, Math.min(w - w / camera.zoom + w / 2, camera.x));
  camera.y = Math.max(-h / 2, Math.min(h - h / camera.zoom + h / 2, camera.y));
  $('board').setAttribute('viewBox', `${camera.x} ${camera.y} ${w / camera.zoom} ${h / camera.zoom}`);
  $('zoomLabel').textContent = `${Math.round(camera.zoom * 100)}%`;
  $('zoom-out').disabled = camera.zoom <= 1; $('zoom-in').disabled = camera.zoom >= 12;
}
function fit() { camera = {x: 0, y: 0, zoom: 1}; updateCamera(); }
function worldPoint(x, y) {
  const p = $('board').createSVGPoint(); p.x = x; p.y = y;
  return p.matrixTransform($('board').getScreenCTM().inverse());
}
function zoom(factor, anchor = null) {
  if (!data) return;
  anchor ||= {x: camera.x + data.map.width * size / camera.zoom / 2, y: camera.y + data.map.height * size / camera.zoom / 2};
  const next = Math.max(1, Math.min(12, camera.zoom * factor)), ratio = next / camera.zoom;
  camera.x = anchor.x - (anchor.x - camera.x) / ratio;
  camera.y = anchor.y - (anchor.y - camera.y) / ratio;
  camera.zoom = next; if (next === 1) fit(); else updateCamera();
}
function render() {
  if (!data) return;
  const record = currentRecord(), state = currentState();
  $('turn').value = turn; $('jump').value = turn;
  $('turnLabel').textContent = turn ? `第 ${turn} / ${last} 回合` : '初始局面 · 回合 0';
  $('prev').disabled = turn === 0; $('next').disabled = turn === last; $('play').disabled = last === 0;
  $('frameNote').textContent = turn ? ($('phase').value === 'start' ? 'AI 决策前局面' : '移动、生成与得分后') : '';
  $('result').textContent = state.outcome ? (state.outcome.winners.length === 1 ? `队伍 ${state.outcome.winners[0]} 获胜` : `平局：${state.outcome.winners.join('、')}`) : '';
  for (const name of ['sites-layer', 'flags-layer', 'shots-layer', 'unit-layer', 'health-bars']) $(name).replaceChildren();
  for (const p of data.map.flag_points) {
    const circle = svg('circle', {cx: (p.x + .5) * size, cy: (p.y + .5) * size, r: 11, fill: 'none', stroke: '#f0bd65', 'stroke-width': 1.5, 'stroke-dasharray': '3 2'}, undefined, $('sites-layer'));
    const s = state.sites.find(v => v.site_id === p.id);
    svg('title', {}, `旗点 ${p.id}` + (s.active_flag_id ? ` · 关联旗 ${s.active_flag_id}` : ` · 第 ${s.next_attempt_turn} 回合尝试`), circle);
  }
  for (const f of state.flags) if (f.location.state === 'ground') {
    const p = f.location.position;
    svg('text', {x: (p.x + .5) * size, y: (p.y + .73) * size, fill: '#ffd166', 'font-size': 24, 'text-anchor': 'middle'}, '⚑', $('flags-layer'));
  }
  if (record && $('shots').checked && $('phase').value === 'end') for (const e of record.frame.events) if (e.type === 'shot' && e.validation === 'ok' && e.from) {
    const p = e.blocked_by || e.target;
    svg('line', {x1: (e.from.x + .5) * size, y1: (e.from.y + .5) * size, x2: (p.x + .5) * size, y2: (p.y + .5) * size, stroke: e.result === 'hit' ? '#fff1b3' : '#a5b3c1', 'stroke-width': 2, opacity: .8, 'stroke-dasharray': e.result === 'hit' ? 'none' : '4 3'}, undefined, $('shots-layer'));
    svg('circle', {cx: (e.target.x + .5) * size, cy: (e.target.y + .5) * size, r: 6, fill: 'none', stroke: '#ffe49c', 'stroke-width': 1.4}, undefined, $('shots-layer'));
  }
  for (const u of state.units) if (u.position) {
    const cx = (u.position.x + .5) * size, cy = (u.position.y + .55) * size;
    const group = svg('g', {'data-unit': label(u.id)}, undefined, $('unit-layer'));
    svg('title', {}, unitText(u), group);
    svg('circle', {cx, cy, r: 10, fill: colors[u.id.team_id], stroke: selected === label(u.id) ? '#ffffff' : '#071018', 'stroke-width': selected === label(u.id) ? 2.5 : 1.5}, undefined, group);
    svg('text', {x: cx, y: cy + 4, fill: '#101a22', 'font-size': 13, 'font-weight': 800, 'text-anchor': 'middle'}, label(u.id), group);
    if (u.carrying !== null) svg('text', {x: cx + 6, y: cy - 4, fill: '#ffe28a', 'font-size': 16}, '⚑', group);
    if (u.hp < 3) for (let i = 0; i < 3; i++) svg('rect', {x: cx - 10 + i * 7, y: cy - 16, width: 6, height: 4, rx: 1, fill: i < u.hp ? '#86e0a5' : '#3c4a58', stroke: '#0b1117', 'stroke-width': .6}, undefined, $('health-bars'));
  }
  $('selection').textContent = selected ? unitText(state.units.find(u => label(u.id) === selected)) : '点击棋子查看状态 · ⚑ 携旗 · 受伤显示三格血条';
  $('scores').replaceChildren();
  for (const team of data.manifest.teams) {
    const row = document.createElement('div'); row.className = 'team'; row.style.setProperty('--team', colors[team.team_id]); row.title = `${team.team_id} · ${team.name}`;
    const name = document.createElement('span'); name.className = 'team-name'; name.append(document.createTextNode(`队 ${team.team_id} `));
    const bot = document.createElement('span'); bot.className = 'bot-name'; bot.textContent = team.name; name.append(bot);
    const score = document.createElement('b'); score.textContent = state.scores[team.team_id]; row.append(name, score); $('scores').append(row);
  }
  $('units').replaceChildren();
  for (const u of state.units) {
    const row = document.createElement('div'); row.className = 'unit';
    const a = document.createElement('span'); a.textContent = `${label(u.id)} · ${pos(u.position)}`; a.style.color = colors[u.id.team_id];
    const b = document.createElement('span'); b.textContent = u.position ? `HP ${u.hp}/3 · ${flags(u.carrying)}` : `死亡 · 第 ${u.respawn_at_turn} 回合复活`;
    row.append(a, b); $('units').append(row);
  }
  $('calls').replaceChildren();
  for (const c of record?.calls || []) {
    const row = document.createElement('div'); row.className = 'call'; row.textContent = `队 ${c.team_id} · ${c.status} · ${(c.elapsed_us / 1000).toFixed(2)} ms`;
    if (c.init_elapsed_us || c.error) { const note = document.createElement('small'); note.textContent = `${c.init_elapsed_us ? `初始化 ${(c.init_elapsed_us / 1000).toFixed(1)} ms · ` : ''}${c.error || ''}`; row.append(note); }
    $('calls').append(row);
  }
  if (!record) $('calls').textContent = '初始局面尚未调用 AI';
  $('events').replaceChildren();
  for (const e of record?.frame.events || []) {
    const details = document.createElement('details'), summary = document.createElement('summary'), tag = document.createElement('span'), body = document.createElement('pre');
    tag.className = 'tag'; tag.textContent = e.phase; summary.append(tag, document.createTextNode(eventText(e)));
    body.textContent = JSON.stringify(e, null, 2); details.append(summary, body); $('events').append(details);
  }
  if (!record?.frame.events.length) $('events').textContent = turn ? '本回合无事件' : '初始随机出生与旗帜布局';
}
function pause() { if (timer) clearInterval(timer); timer = null; $('play').textContent = '播放'; }
function jump(value) { if (!data) return; turn = Math.max(0, Math.min(last, Math.floor(Number(value) || 0))); render(); }
function install(payload, name) {
  validateReplay(payload);
  pause(); drag = null; $('board').classList.remove('dragging'); selected = null;
  data = payload; last = data.records.length; turn = 0; $('phase').value = 'end';
  $('empty').hidden = true; $('workspace').hidden = false; $('loadError').textContent = '';
  $('loadedFile').textContent = name; $('loadedFile').title = name;
  $('turn').max = last; $('jump').max = last;
  $('meta').textContent = `${data.map.id} · ${data.map.width} × ${data.map.height} · ${data.map.players} 队 · 种子 ${data.manifest.seed}`;
  $('scoreGoal').textContent = `目标 ${data.map.match_limits.target_score}`;
  $('warning').textContent = data.manifest.status !== 'complete' ? '记录未完成：仅包含已完整写入的回合。' : '';
  buildBoard(); fit(); render();
}
async function loadFile(file) {
  const generation = ++loadGeneration;
  try {
    if (!file || file.size > maxBytes) throw new Error('回放文件不能超过 512 MiB');
    const raw = await file.text();
    if (generation !== loadGeneration) return;
    install(JSON.parse(raw), file.name);
  } catch (error) {
    if (generation === loadGeneration) $('loadError').textContent = `无法载入回放：${error.message}`;
  }
}
$('file').onchange = event => { const file = event.target.files[0]; event.target.value = ''; if (file) loadFile(file); };
let dragDepth = 0;
document.addEventListener('dragenter', event => { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); dragDepth++; $('dropOverlay').hidden = false; } });
document.addEventListener('dragover', event => { if (event.dataTransfer?.types.includes('Files')) event.preventDefault(); });
document.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('dropOverlay').hidden = true; } });
document.addEventListener('drop', event => {
  event.preventDefault(); dragDepth = 0; $('dropOverlay').hidden = true;
  const files = event.dataTransfer?.files;
  if (files?.length === 1) loadFile(files[0]);
  else if (files?.length) { ++loadGeneration; $('loadError').textContent = '请一次拖入一个 replay.json 数据文件。'; }
});
$('prev').onclick = () => { pause(); jump(turn - 1); }; $('next').onclick = () => { pause(); jump(turn + 1); };
$('turn').oninput = event => { pause(); jump(event.target.value); }; $('jump').onchange = event => { pause(); jump(event.target.value); };
$('play').onclick = () => {
  if (!data || !last) return;
  if (timer) { pause(); return; }
  if (turn === last) jump(0);
  $('play').textContent = '暂停';
  timer = setInterval(() => { jump(turn + 1); if (turn >= last) pause(); }, 1000 / Number($('speed').value));
};
$('speed').onchange = () => { if (timer) { pause(); $('play').click(); } };
$('phase').onchange = render; $('shots').onchange = render;
for (const tab of document.querySelectorAll('[data-tab]')) tab.onclick = () => {
  for (const button of document.querySelectorAll('[data-tab]')) {
    const active = button === tab; button.setAttribute('aria-selected', String(active)); $(button.dataset.tab).hidden = !active;
  }
};
$('zoom-in').onclick = () => zoom(1.4); $('zoom-out').onclick = () => zoom(1 / 1.4); $('fit').onclick = fit;
$('fullscreen').onclick = async () => {
  try { if (document.fullscreenElement) await document.exitFullscreen(); else await $('arena').requestFullscreen(); }
  catch (error) { $('loadError').textContent = `无法进入全屏：${error.message}`; }
};
document.addEventListener('fullscreenchange', () => { $('fullscreen').textContent = document.fullscreenElement ? '退出全屏' : '全屏'; });
$('board').addEventListener('wheel', event => { if (!data) return; event.preventDefault(); zoom(Math.exp(-Math.max(-300, Math.min(300, event.deltaY)) * .002), worldPoint(event.clientX, event.clientY)); }, {passive: false});
$('board').addEventListener('pointerdown', event => {
  if (!data || event.button !== 0 || drag) return;
  const matrix = $('board').getScreenCTM();
  drag = {id: event.pointerId, x: event.clientX, y: event.clientY, camera: {...camera}, scale: matrix.a, moved: false, unit: event.target.closest('[data-unit]')?.dataset.unit};
  $('board').setPointerCapture(event.pointerId); $('board').classList.add('dragging');
});
$('board').addEventListener('pointermove', event => {
  if (!drag || drag.id !== event.pointerId) return;
  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
  drag.moved ||= Math.hypot(dx, dy) > 4;
  if (drag.moved) { camera.x = drag.camera.x - dx / drag.scale; camera.y = drag.camera.y - dy / drag.scale; updateCamera(); }
});
function endDrag(event) {
  if (!drag || drag.id !== event.pointerId) return;
  const selection = !drag.moved && event.type === 'pointerup' ? drag.unit : null;
  drag = null; $('board').classList.remove('dragging');
  if ($('board').hasPointerCapture(event.pointerId)) $('board').releasePointerCapture(event.pointerId);
  if (selection) { selected = selection; render(); }
}
for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) $('board').addEventListener(type, endDrag);
document.addEventListener('keydown', event => {
  if (['INPUT', 'SELECT', 'BUTTON', 'SUMMARY'].includes(event.target.tagName) || !data) return;
  if (event.key === 'ArrowRight') $('next').click(); if (event.key === 'ArrowLeft') $('prev').click();
  if (event.code === 'Space') { event.preventDefault(); $('play').click(); }
});
try {
  const embedded = JSON.parse($('replay-data').textContent);
  if (embedded) install(embedded, '内嵌回放');
} catch (error) { $('loadError').textContent = `内嵌回放无效：${error.message}`; }
