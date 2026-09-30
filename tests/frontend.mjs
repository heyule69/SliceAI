import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve, dirname, basename } from 'node:path';
import { pathToFileURL } from 'node:url';
import { test, after } from 'node:test';
import ts from 'typescript';

// Transpile the actual controller and pure helpers. The bridge supplies deferred
// responses so the race is repeatable without a desktop window or real AI calls.
const temporary = await mkdtemp(join(tmpdir(), 'sliceai-frontend-'));
after(async () => {
  assert.equal(resolve(dirname(temporary)), resolve(tmpdir()));
  assert.match(basename(temporary), /^sliceai-frontend-/);
  await rm(temporary, { recursive: true, force: true });
});
for (const name of ['workspace-state', 'fine-wizard', 'fine-progress', 'segment-player', 'fine']) {
  let source = await readFile(resolve('src', `${name}.ts`), 'utf8');
  source = source.replace(/^import '[^']+\.css';\s*/gm, '')
    .replace(/'\.\/(workspace-state|fine-wizard|fine-progress|segment-player)'/g, "'./$1.mjs'")
    .replace(/'@tauri-apps\/(api\/core|api\/event|plugin-dialog)'/g, "'./bridge.mjs'");
  await writeFile(join(temporary, `${name}.mjs`), ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
  } }).outputText, 'utf8');
}
await writeFile(join(temporary, 'bridge.mjs'), `
export const invoke = (...args) => globalThis.testBridge.invoke(...args);
export const listen = async (...args) => { globalThis.testBridge.listeners.push(args[1]); return () => {}; };
export const open = (...args) => globalThis.testBridge.open(...args);
export const convertFileSrc = value => value;
export const isTauri = () => true;
`, 'utf8');

class MemoryStorage {
  values = new Map();
  get length() { return this.values.size; }
  key(index) { return [...this.values.keys()][index] ?? null; }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
  removeItem(key) { this.values.delete(key); }
}
globalThis.localStorage = new MemoryStorage();
const finePage = { hidden: true, innerHTML: '' };
globalThis.document = { addEventListener() {}, getElementById: id => id === 'finePage' ? finePage : null };
globalThis.window = { addEventListener() {} };
globalThis.testBridge = { listeners: [], invoke: async () => {}, open: async () => null };
const { bindImportedVideo, sameView, SubtitleDrafts, globalActivity } = await import(pathToFileURL(join(temporary, 'workspace-state.mjs')));
const { FineWorkspace } = await import(pathToFileURL(join(temporary, 'fine.mjs')));
const { SegmentPlayer } = await import(pathToFileURL(join(temporary, 'segment-player.mjs')));
const { cutResult, cutSummaryHtml, cutLedgerHtml, executionOutcome } = await import(pathToFileURL(join(temporary, 'fine-progress.mjs')));
const cues = [{ id: 1, start: 0, end: 1, text: '原字幕' }];
const changed = [{ ...cues[0], text: '核对后的字幕' }];
const project = (id, revision = 1) => ({ id, task_id: `task-${id}`, clip_id: 1,
  revision, title: id, status: 'idle', stage: '', error: '', source_start: 0,
  source_end: 10, current_version: `v-${id}`, versions: [{ id: `v-${id}`, cues, ranges: [], duration: 10, preview: '', subtitles: true }], exports: [], messages: [] });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function workspace() {
  const fine = new FineWorkspace(() => {}, () => {}, async () => {});
  fine.renderQuestions = () => {};
  fine.p = project('A');
  return fine;
}

async function withExportWorkspace(chooseDirectory, check) {
  const getElementById = document.getElementById, open = testBridge.open;
  const requests = [], openings = [], messages = [], nodes = new Map();
  const modal = { open: false, shown: 0, closed: 0,
    showModal() { this.open = true; this.shown++; },
    close() { this.open = false; this.closed++; } };
  const srt = { checked: false };
  const decode = value => value.replace(/&quot;|&#39;|&lt;|&gt;|&amp;/g,
    entity => ({ '&quot;': '"', '&#39;': "'", '&lt;': '<', '&gt;': '>', '&amp;': '&' })[entity]);
  let html = '';
  const content = { get innerHTML() { return html; }, set innerHTML(value) {
    html = value;
    for (const [id, node] of nodes) if (node.readOnly) nodes.delete(id);
    srt.checked = /<input\b[^>]*\bid="fineSrt"[^>]*\bchecked\b/i.test(value);
    for (const input of value.matchAll(/<input\b[^>]*>/gi)) {
      const id = input[0].match(/\bid="([^"]+)"/), path = input[0].match(/\bvalue="([^"]*)"/);
      if (id && /\breadonly\b/i.test(input[0])) nodes.set(id[1], { readOnly: true, value: decode(path?.[1] || '') });
    }
  } };
  nodes.set('modal', modal); nodes.set('modalContent', content); nodes.set('fineSrt', srt);
  document.getElementById = id => nodes.get(id) ?? getElementById.call(document, id);
  testBridge.open = async options => { openings.push(options); return chooseDirectory(options); };
  try {
    const fine = new FineWorkspace(() => {}, message => messages.push(message), async () => {});
    fine.renderQuestions = () => {}; fine.render = () => {};
    fine.p = project('A'); fine.current().confirmed = true;
    fine.queue = async (cmd, values) => { requests.push({ cmd, values }); };
    await check({ fine, requests, openings, messages, modal, content, srt,
      directoryField: () => [...nodes.values()].find(node => node.readOnly) });
  } finally {
    document.getElementById = getElementById; testBridge.open = open;
  }
}

test('changing recordings clears both attachments and resets the selected audio track', () => {
  assert.deepEqual(bindImportedVideo({ video: 'D:\\A.mp4', subtitle: 'A.srt', chat: 'A.xml', audioTrack: 2 }, 'D:\\B.mp4'),
    { video: 'D:\\B.mp4', subtitle: '', chat: '', audioTrack: 0 });
  const same = bindImportedVideo({ video: 'D:\\A.mp4', subtitle: 'A.srt', chat: 'A.xml', audioTrack: 2 }, 'd:/a.mp4');
  assert.equal(same.subtitle, 'A.srt'); assert.equal(same.audioTrack, 2);
});

test('view tickets reject another project and a later opening of the same project', () => {
  assert.equal(sameView({ projectId: 'A', generation: 1 }, 'B', 1), false);
  assert.equal(sameView({ projectId: 'A', generation: 1 }, 'A', 2), false);
});

test('a delayed prepare enqueues the original project and cannot overwrite the next view', async () => {
  const waiting = deferred(), enqueued = [];
  testBridge.invoke = async (method, payload) => {
    if (method === 'enqueue') { enqueued.push(payload.request); return; }
    if (payload.request.cmd === 'edit_prepare') return waiting.promise;
    throw Error(`unexpected call ${payload.request.cmd}`);
  };
  const fine = workspace(), operation = fine.queue('edit_auto', { options: { cleanup: ['silence'] } });
  fine.p = project('B'); fine.sourceToken++; fine.pending = false;
  waiting.resolve({ ...project('A', 2), status: 'queued' }); await operation;
  assert.equal(enqueued[0].project_id, 'A'); assert.equal(enqueued[0].revision, 2);
  assert.equal(fine.p.id, 'B'); assert.equal(fine.pending, false);
});

test('enqueue failure abandons the original project without changing the next view', async () => {
  const waiting = deferred(), abandoned = [];
  testBridge.invoke = async (method, payload) => {
    if (method === 'enqueue') throw Error('queue unavailable');
    if (payload.request.cmd === 'edit_prepare') return waiting.promise;
    if (payload.request.cmd === 'edit_abandon') { abandoned.push(payload.request.project_id); return project('A', 3); }
  };
  const fine = workspace(), operation = fine.queue('edit_auto');
  fine.p = project('B'); fine.sourceToken++; fine.pending = false;
  waiting.resolve({ ...project('A', 2), status: 'queued' });
  await assert.rejects(operation, /queue unavailable/);
  assert.deepEqual(abandoned, ['A']); assert.equal(fine.p.id, 'B');
});

test('delayed choice saves cannot overwrite another project or advance its wizard', async () => {
  const waiting = deferred(); testBridge.invoke = async () => waiting.promise;
  const fine = workspace(), saving = fine.saveChoices(5);
  fine.p = project('B'); fine.sourceToken++; fine.step = 0; fine.saving = false;
  waiting.resolve(project('A', 2));
  assert.equal(await saving, false); assert.equal(fine.p.id, 'B'); assert.equal(fine.step, 0);
});

test('late source reads cannot replace a newly opened recording', async () => {
  const waiting = deferred();
  testBridge.invoke = async (method, payload) => payload.request.cmd === 'edit_get'
    ? project(payload.request.project_id) : payload.request.project_id === 'A' ? waiting.promise : { path: 'B.mp4', start: 0, end: 10 };
  const fine = workspace(), loadingA = fine.openProject('A');
  await Promise.resolve(); await Promise.resolve();
  const loadingB = fine.openProject('B'); await loadingB;
  waiting.resolve({ path: 'A.mp4', start: 0, end: 10 }); await loadingA;
  assert.equal(fine.p.id, 'B'); assert.equal(fine.source, 'B.mp4');
});

test('subtitle drafts survive fresh controllers and remain scoped to project and version', () => {
  const storage = new MemoryStorage(), drafts = new SubtitleDrafts(storage);
  drafts.write('A', 'v1', cues, changed);
  const reloaded = new SubtitleDrafts(storage);
  assert.deepEqual(reloaded.read('A', 'v1', cues), changed);
  assert.equal(reloaded.read('B', 'v1', cues), null);
  assert.equal(reloaded.read('A', 'v2', cues), null);
  assert.equal(reloaded.read('A', 'v1', [{ ...cues[0], text: '服务器新文字' }]), null);
  const recovered = reloaded.read('A', 'v1', cues); recovered[0].text = 'temporary';
  assert.deepEqual(reloaded.read('A', 'v1', cues), changed);
});

test('successful submission cannot delete a newer local draft and task deletion removes drafts', () => {
  const drafts = new SubtitleDrafts(new MemoryStorage());
  drafts.write('A', 'v1', cues, changed);
  drafts.removeSubmitted('A', 'v1', cues, [{ ...changed[0], text: 'older submission' }]);
  assert.deepEqual(drafts.read('A', 'v1', cues), changed);
  drafts.removeSubmitted('A', 'v1', cues, changed); assert.equal(drafts.read('A', 'v1', cues), null);
  drafts.write('A', 'v1', cues, changed); drafts.write('A', 'v2', cues, changed);
  drafts.removeProject('A'); assert.equal(drafts.read('A', 'v1', cues), null); assert.equal(drafts.read('A', 'v2', cues), null);
});

test('storage failure keeps subtitle edits in the window and reports the failure', () => {
  let errors = 0; const storage = new MemoryStorage(); storage.setItem = () => { throw Error('quota'); };
  const drafts = new SubtitleDrafts(storage, () => errors++); assert.equal(drafts.write('A', 'v1', cues, changed), false);
  assert.equal(errors, 1); assert.deepEqual(drafts.read('A', 'v1', cues), changed);
});

test('global status includes background fine work and waiting queue entries', () => {
  assert.match(globalActivity([], [{ status: 'busy' }], []), /1 个细剪任务/);
  assert.match(globalActivity([], [], [{ status: 'queued' }]), /1 项排队/);
  assert.equal(globalActivity([], [], []), '就绪');
});

test('a selected audio track never silently starts playback from the original multi-track file', () => {
  const messages = [], video = { style: {}, pause() {}, load() {}, removeAttribute() {}, src: '' };
  const player = { key: '', video, play: {}, seekbar: {}, clock: {}, message: value => messages.push(value),
    offerCompatible: (message, label) => messages.push([message, label]) };
  SegmentPlayer.prototype.set.call(player, { path: 'recording.mkv', start: 2, end: 12, audio_track: 1, compatible_required: true }, 'recording.mkv', true);
  assert.equal(video.src, ''); assert.equal(player.play.disabled, true); assert.equal(player.seekbar.disabled, true);
  assert.deepEqual(messages.at(-1), ['音轨 2 需要先准备预览', '准备所选音轨预览']);
  SegmentPlayer.prototype.set.call(player, { path: 'prepared.mp4', start: 0, end: 10 }, 'prepared.mp4');
  assert.equal(video.src, 'prepared.mp4#t=0,10'); assert.equal(player.play.disabled, false);
});

test('worker interruption retains drafts and unlocks the current project for retry', () => {
  const fine = workspace(); fine.cues = structuredClone(changed); fine.pending = true;
  fine.receive({ type: 'error', project_id: 'A', cmd: 'edit_auto', message: 'worker stopped' });
  assert.equal(fine.p.status, 'interrupted'); assert.equal(fine.pending, false);
  assert.deepEqual(fine.cues, changed); assert.equal(fine.wizard, false);
});

test('zero effective cuts report unchanged duration and the actual blocked decisions', () => {
  const version = { duration: 429.4, removed_duration: 60, auto_review: { applied_removals: 9 },
    cut_ledger: [{ id: 'repeat-1', start: 17860, end: 17862, text: '那个那个', reason: '重复表达', status: 'blocked', block_reason: '无法确认字尾，保留原声' },
      { id: 'filler-2', start: null, end: null, quote: '嗯', reason: '语气词', status: 'blocked', block_reason: '暂时无法定位' }] };
  const result = cutResult(version, 17853.136, 18282.534);
  assert.equal(result.unchanged, true); assert.equal(result.removedDuration, 0);
  assert.equal(result.suggested, 2); assert.equal(result.blocked, 2); assert.equal(result.applied, 0);
  const html = cutSummaryHtml(version, 17853.136, 18282.534);
  assert.match(html, /未产生有效精简/); assert.match(html, /实际应用 0 处/);
  assert.match(html, /无法确认字尾，保留原声/); assert.doesNotMatch(html, /实际精简 60/);
  assert.match(executionOutcome({ error: '', stage: '', status: 'idle', execution: { state: 'done', command: 'edit_auto' } }, true, result.unchanged), /处理结束/);
});

test('cut ledger displays source-relative times, escaped quotes, and restores only applied candidates', () => {
  const version = { duration: 8, cut_ledger: [
    { id: 'cut<&"1', start: 103, end: 105, text: '<img src=x>就就是', reason: '重复重说', status: 'applied' },
    { id: 'no-location', start: null, end: null, quote: '那个', reason: '语气词', status: 'blocked', block_reason: '无法定位' },
    { id: 'already-restored', start: 106, end: 107, text: '后续结局', reason: '用户恢复', status: 'restored' },
  ] };
  const result = cutResult(version, 100, 110);
  assert.equal(result.removedDuration, 2); assert.equal(result.applied, 1); assert.equal(result.blocked, 1);
  const html = cutLedgerHtml(version, 100);
  assert.match(html, /00:03.00 — 00:05.00/); assert.match(html, /data-seconds="103"/);
  assert.match(html, /&lt;img src=x&gt;/); assert.doesNotMatch(html, /<img src=x>/);
  assert.equal((html.match(/data-fine-action="restore-candidate"/g) || []).length, 1);
  assert.match(html, /data-candidate="cut&lt;&amp;&quot;1"/); assert.match(html, /暂时无法定位/); assert.match(html, /已恢复/);
  assert.match(cutLedgerHtml(version, 100, true), /data-candidate="cut&lt;&amp;&quot;1" disabled/);
});

test('restoring a cut submits the candidate ID and leaves source playback until a new preview is ready', async () => {
  const fine = workspace(), requests = [];
  fine.p.versions[0].cut_ledger = [
    { id: 'repeat-at-3', start: 3, end: 5, text: '就就是', reason: '重复重说', status: 'applied' },
    { id: 'protected-end', start: 8, end: 9, text: '退钱结局', reason: '保留剧情', status: 'blocked' },
  ];
  fine.mode = 'preview'; fine.cues = structuredClone(changed);
  fine.queue = async (cmd, values) => { requests.push({ cmd, values }); };
  await fine.action('restore-candidate', { dataset: { candidate: 'repeat-at-3' } });
  assert.deepEqual(requests, [{ cmd: 'edit_update', values: { restore_candidate_id: 'repeat-at-3' } }]);
  assert.equal(fine.mode, 'source'); assert.equal(fine.cues, null);
  await fine.action('restore-candidate', { dataset: { candidate: 'protected-end' } });
  await fine.action('restore-candidate', { dataset: { candidate: 'missing-cut' } });
  assert.equal(requests.length, 1);
  fine.p.versions[0].cut_ledger[0].status = 'restored';
  await fine.action('restore-candidate', { dataset: { candidate: 'repeat-at-3' } });
  assert.equal(requests.length, 1);
});

test('a reviewed keep decision is retained without a misleading pending action or restore button', () => {
  const version = { duration: 10, cut_ledger: [
    { id: 'story-ending', start: 103, end: 105, text: '后续结局', reason: '故事的回应需要保留', kind: 'semantic', status: 'suggested', decision: 'keep' },
  ] };
  const html = cutLedgerHtml(version, 100);
  assert.match(html, /已保留/); assert.doesNotMatch(html, /待处理|restore-candidate/);
  const legacy = { duration: 10, cut_ledger: [{ ...version.cut_ledger[0], decision: undefined }] };
  assert.match(cutLedgerHtml(legacy, 100), /已保留/);
  assert.match(cutLedgerHtml(legacy, 100, true), /待处理/);
});

test('partially deleted candidates show each effective cut rather than the full original candidate', () => {
  const version = { duration: 8, cut_ledger: [
    { id: 'partial', start: 102, end: 108, text: '原候选文字', reason: '手动重新删除其中两段', status: 'applied', decision: 'manual',
      effective_intervals: [{ start: 103, end: 104 }, { start: 106, end: 107 }] },
  ] };
  const html = cutLedgerHtml(version, 100);
  assert.match(html, /00:03.00 — 00:04.00/); assert.match(html, /00:06.00 — 00:07.00/);
  assert.doesNotMatch(html, /00:02.00 — 00:08.00|data-seconds="102"/);
  assert.match(html, /data-seconds="103"/); assert.match(html, /data-seconds="106"/);
  assert.match(html, /手动应用/); assert.match(html, /restore-candidate/);
  version.cut_ledger[0].effective_intervals = [];
  assert.doesNotMatch(cutLedgerHtml(version, 100), /restore-candidate|data-seconds=/);
});

test('fine export selects a directory and submits that path, SRT choice, and the confirmed version', async () => {
  const directory = 'D:\\Exports\\精剪成片';
  await withExportWorkspace(async () => directory, async ({ fine, requests, openings, modal, content, srt, directoryField }) => {
    await fine.action('export', { dataset: {} });
    assert.equal(openings.length, 1);
    assert.equal(openings[0].directory, true); assert.equal(openings[0].multiple, false);
    assert.equal(openings[0].title, '选择成片保存文件夹');
    assert.equal(modal.shown, 1); assert.equal(modal.open, true); assert.deepEqual(requests, []);
    assert.match(content.innerHTML, /fineSrt/);
    assert.equal(directoryField()?.readOnly, true); assert.equal(directoryField()?.value, directory);
    srt.checked = true;
    await fine.action('export-confirm', { dataset: {} });
    assert.deepEqual(requests, [{ cmd: 'edit_export', values: { export_dir: directory, srt: true, version_id: 'v-A' } }]);
    assert.equal(modal.open, false);
  });
});

test('canceling the export directory picker creates neither a confirmation modal nor a task', async () => {
  await withExportWorkspace(async () => null, async ({ fine, requests, openings, modal }) => {
    await fine.action('export', { dataset: {} });
    assert.equal(openings.length, 1); assert.equal(modal.shown, 0); assert.equal(modal.open, false);
    assert.deepEqual(requests, []);
    await fine.action('export-confirm', { dataset: {} });
    assert.deepEqual(requests, []);
  });
});

test('a delayed export directory cannot open a modal or enqueue work after changing projects', async () => {
  const waiting = deferred();
  await withExportWorkspace(() => waiting.promise, async ({ fine, requests, openings, modal }) => {
    const selecting = fine.action('export', { dataset: {} });
    assert.equal(openings.length, 1);
    fine.p = project('B'); fine.current().confirmed = true; fine.sourceToken++;
    waiting.resolve('D:\\Exports\\old-project'); await selecting;
    assert.equal(fine.p.id, 'B'); assert.equal(modal.shown, 0); assert.deepEqual(requests, []);
  });
});

test('a delayed export directory cannot open a modal or enqueue work after changing versions', async () => {
  const waiting = deferred();
  await withExportWorkspace(() => waiting.promise, async ({ fine, requests, openings, modal }) => {
    const selecting = fine.action('export', { dataset: {} });
    assert.equal(openings.length, 1);
    fine.p.versions.push({ ...fine.current(), id: 'v-A-restored', confirmed: true });
    fine.p.current_version = 'v-A-restored';
    waiting.resolve('D:\\Exports\\old-version'); await selecting;
    assert.equal(fine.current().id, 'v-A-restored'); assert.equal(modal.shown, 0); assert.deepEqual(requests, []);
  });
});

test('an export confirmation rejects a version changed while the modal was open', async () => {
  await withExportWorkspace(async () => 'D:\\Exports\\chosen', async ({ fine, requests, messages, modal }) => {
    await fine.action('export', { dataset: {} }); assert.equal(modal.open, true);
    fine.p.versions.push({ ...fine.current(), id: 'v-A-new', confirmed: true });
    fine.p.current_version = 'v-A-new';
    await fine.action('export-confirm', { dataset: {} });
    assert.deepEqual(requests, []); assert.ok(messages.length > 0);
  });
});

test('an unconfirmed fine version cannot select an export directory or submit work', async () => {
  await withExportWorkspace(async () => 'D:\\Exports\\chosen', async ({ fine, requests, openings, modal }) => {
    fine.current().confirmed = false;
    await fine.action('export', { dataset: {} });
    assert.deepEqual(openings, []); assert.equal(modal.shown, 0); assert.deepEqual(requests, []);
  });
});

test('changing the export folder updates the destination and canceling a later change retains it', async () => {
  const original = 'D:\\Exports\\first', changedDirectory = 'E:\\Finished\\second';
  const selections = [original, changedDirectory, null];
  await withExportWorkspace(async () => selections.shift(), async ({ fine, requests, openings, modal, srt, directoryField }) => {
    await fine.action('export', { dataset: {} });
    srt.checked = true;
    await fine.action('export-folder', { dataset: {} });
    assert.equal(directoryField()?.value, changedDirectory); assert.equal(srt.checked, true);
    await fine.action('export-folder', { dataset: {} });
    assert.equal(directoryField()?.value, changedDirectory); assert.equal(modal.open, true); assert.equal(srt.checked, true);
    assert.equal(openings.length, 3); assert.deepEqual(requests, []);
    await fine.action('export-confirm', { dataset: {} });
    assert.deepEqual(requests, [{ cmd: 'edit_export', values: { export_dir: changedDirectory, srt: true, version_id: 'v-A' } }]);
  });
});

test('repeated export clicks share one pending directory selection and create no task', async () => {
  const waiting = deferred();
  await withExportWorkspace(() => waiting.promise, async ({ fine, requests, openings, modal }) => {
    const first = fine.action('export', { dataset: {} }), second = fine.action('export', { dataset: {} });
    const count = openings.length;
    waiting.resolve('D:\\Exports\\chosen'); await Promise.all([first, second]);
    assert.equal(count, 1); assert.equal(modal.shown, 1); assert.deepEqual(requests, []);
  });
});

test('a rejected directory picker releases the selection lock and allows a fresh export', async () => {
  const directory = 'D:\\Exports\\retry'; let attempts = 0;
  await withExportWorkspace(async () => {
    if (attempts++ === 0) throw Error('directory picker unavailable');
    return directory;
  }, async ({ fine, requests, openings, messages, modal }) => {
    await fine.guard(() => fine.action('export', { dataset: {} }));
    assert.equal(openings.length, 1); assert.equal(modal.shown, 0); assert.deepEqual(requests, []);
    assert.deepEqual(messages, ['directory picker unavailable']);
    await fine.action('export', { dataset: {} });
    assert.equal(openings.length, 2); assert.equal(modal.shown, 1); assert.deepEqual(requests, []);
    await fine.action('export-confirm', { dataset: {} });
    assert.deepEqual(requests, [{ cmd: 'edit_export', values: { export_dir: directory, srt: false, version_id: 'v-A' } }]);
  });
});
