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
