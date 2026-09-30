/** Small state helpers shared by the desktop views and deterministic regressions. */
export type ViewTicket = { projectId: string; generation: number };
export function sameView(ticket: ViewTicket, projectId: string | undefined, generation: number) {
  return ticket.projectId === projectId && ticket.generation === generation;
}

const normalizedPath = (value: string) => value.replace(/\\/g, '/').toLowerCase();
export type ImportFiles = { video: string; subtitle: string; chat: string; audioTrack: number };
export function bindImportedVideo(files: ImportFiles, video: string): ImportFiles {
  const changed = !!files.video && normalizedPath(files.video) !== normalizedPath(video);
  return { video, subtitle: changed ? '' : files.subtitle, chat: changed ? '' : files.chat,
    audioTrack: changed ? 0 : files.audioTrack };
}
export function sameImportedVideo(left: string, right: string) {
  return normalizedPath(left) === normalizedPath(right);
}

export type DraftCue = { id: number; start: number; end: number; text: string };
type Draft = { baseline: string; cues: DraftCue[] };
type TextStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem' | 'key' | 'length'>;
export const cueFingerprint = (cues: DraftCue[]) => JSON.stringify(cues);
const draftKey = (projectId: string, versionId: string) => `fine-cues:${projectId}:${versionId}`;

/** Version-specific drafts never overwrite server cues or another project's draft. */
export class SubtitleDrafts {
  private memory = new Map<string, Draft>();
  constructor(private storage: TextStorage, private onError: () => void = () => {}) {}
  write(projectId: string, versionId: string, baseline: DraftCue[], cues: DraftCue[]) {
    const key = draftKey(projectId, versionId), draft = { baseline: cueFingerprint(baseline), cues: structuredClone(cues) };
    if (draft.baseline === cueFingerprint(cues)) { this.remove(projectId, versionId); return true; }
    this.memory.set(key, draft);
    try { this.storage.setItem(key, JSON.stringify(draft)); return true; }
    catch { this.onError(); return false; }
  }
  read(projectId: string, versionId: string, baseline: DraftCue[]): DraftCue[] | null {
    const key = draftKey(projectId, versionId);
    try {
      const draft: Draft | null = this.memory.get(key) || JSON.parse(this.storage.getItem(key) || 'null');
      if (!draft || draft.baseline !== cueFingerprint(baseline) || !Array.isArray(draft.cues)) return null;
      if (!draft.cues.every(c => typeof c.text === 'string' && Number.isFinite(c.id) && Number.isFinite(c.start) && Number.isFinite(c.end))) return null;
      return structuredClone(draft.cues);
    } catch { return null; }
  }
  remove(projectId: string, versionId: string) {
    const key = draftKey(projectId, versionId); this.memory.delete(key);
    try { this.storage.removeItem(key); } catch { this.onError(); }
  }
  removeSubmitted(projectId: string, versionId: string, baseline: DraftCue[], submitted: DraftCue[]) {
    const current = this.read(projectId, versionId, baseline);
    if (current && cueFingerprint(current) === cueFingerprint(submitted)) this.remove(projectId, versionId);
  }
  removeProject(projectId: string) {
    const prefix = `fine-cues:${projectId}:`;
    for (const key of this.memory.keys()) if (key.startsWith(prefix)) this.memory.delete(key);
    try {
      for (let i = this.storage.length - 1; i >= 0; i--) {
        const key = this.storage.key(i); if (key?.startsWith(prefix)) this.storage.removeItem(key);
      }
    } catch { this.onError(); }
  }
}

export type QueueEntry = { id: number; cmd: string; task_id?: string; project_id?: string; status: 'queued' | 'running'; position: number };
export function globalActivity(tasks: { status: string }[], edits: { status?: string }[], queue: QueueEntry[]) {
  const taskCount = tasks.filter(t => ['queued','probing','transcribing','analyzing','rendering','exporting','cancelling'].includes(t.status)).length;
  const editCount = edits.filter(p => ['busy','queued'].includes(p.status || '')).length;
  const waiting = queue.filter(q => q.status === 'queued').length;
  const running = queue.some(q => q.status === 'running');
  const parts: string[] = [];
  if (taskCount) parts.push(`${taskCount} 个切片任务`);
  if (editCount) parts.push(`${editCount} 个细剪任务`);
  if (waiting) parts.push(`${waiting} 项排队`);
  return parts.length ? parts.join(' · ') : running ? '正在处理' : '就绪';
}
