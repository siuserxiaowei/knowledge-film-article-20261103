import {readFile, access, realpath} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const canonical = (v) => Array.isArray(v) ? v.map(canonical) : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k => [k,canonical(v[k])])) : v;
const fail = (message) => {throw new Error(message);};
const finite = (v) => typeof v === 'number' && Number.isFinite(v);

try {
  const spec = JSON.parse(await readFile(path.join(root,'content/film.json'),'utf8'));
  const timeline = JSON.parse(await readFile(path.join(root,'src/generated/timeline.json'),'utf8'));
  const hash = createHash('sha256').update(JSON.stringify(canonical(spec))).digest('hex');
  if (timeline.ready !== true) fail('ready=false: run a successful full prepare first; sample does not publish a full film.');
  const report = JSON.parse(await readFile(path.join(root,'content/build-report.json'),'utf8'));
  if (report.status !== 'complete' || report.sample) fail('A successful full preparation report is required.');
  if (timeline.specHash !== hash || report.specHash !== hash) fail('Timeline is stale: film.json changed; rerun python3 tools/prepare_film.py.');
  const defaults = {fps:30,width:1920,height:1080};
  for (const key of ['fps','width','height']) if (!finite(timeline[key]) || timeline[key] !== (spec[key] ?? defaults[key]) || timeline[key] <= 0) fail('Invalid timeline ' + key);
  if (!finite(timeline.durationSeconds) || timeline.durationSeconds <= 0 || timeline.durationInFrames !== Math.round(timeline.durationSeconds * timeline.fps)) fail('Invalid total duration or frame count.');
  if (!Array.isArray(timeline.scenes) || timeline.scenes.length !== spec.scenes.length) fail('Scene count does not match film.json.');
  let last = 0;
  timeline.scenes.forEach((s,i) => {
    if (s.id !== spec.scenes[i].id || s.kind !== spec.scenes[i].kind || s.title !== (spec.scenes[i].title ?? '')) fail('Scene content differs from specification.');
    if (s.kind === 'custom') fail('unimplemented custom scene: implement and register a dedicated scene before export.');
    if (!finite(s.startSeconds) || !finite(s.endSeconds) || s.startSeconds < last - 1e-6 || s.endSeconds <= s.startSeconds || s.endSeconds > timeline.durationSeconds + 1e-5) fail('Invalid scene order or bounds: ' + s.id);
    if (s.startFrame !== Math.round(s.startSeconds * timeline.fps) || s.durationInFrames !== Math.round(s.endSeconds * timeline.fps) - s.startFrame) fail('Scene rounding differs from absolute timeline: ' + s.id);
    last = s.endSeconds;
  });
  const lines = spec.scenes.flatMap(s => (s.lines ?? []).map(l => ({...l,sceneId:s.id})));
  if (!Array.isArray(timeline.captions) || timeline.captions.length !== lines.length) fail('Caption count differs from the actual script.');
  last = 0;
  timeline.captions.forEach((c,i) => {
    if (c.id !== lines[i].id || c.text !== lines[i].text || c.sceneId !== lines[i].sceneId) fail('Caption text differs from the oral script.');
    const scene = timeline.scenes.find(s => s.id === c.sceneId);
    if (!finite(c.startSeconds) || !finite(c.endSeconds) || c.startSeconds < last - 1e-6 || c.endSeconds <= c.startSeconds || c.startSeconds < scene.startSeconds - 1e-6 || c.endSeconds > scene.endSeconds + 1e-6) fail('Caption timing is out of bounds.');
    if (c.startFrame !== Math.round(c.startSeconds * timeline.fps) || c.endFrame !== Math.round(c.endSeconds * timeline.fps)) fail('Caption frame rounding is stale.');
    last = c.endSeconds;
  });
  if (typeof timeline.narrated !== 'boolean') fail('Narration status must be explicit.');
  const mode = spec.audio?.mode ?? 'silent';
  if (mode === 'silent' && timeline.narrated) fail('Silent mode cannot claim real narration.');
  if (mode !== 'silent' && lines.length && !timeline.narrated) fail('Requested real narration has not been prepared.');
  const audioGate = spawnSync('python3',[path.join(root,'tools/audio_guard.py'),'--project',root],{encoding:'utf8'});
  if (audioGate.error?.code === 'ENOENT') fail('python3 is missing.');
  if (audioGate.status !== 0) fail((audioGate.stderr || audioGate.stdout || 'Audio provenance/alignment guard failed.').trim());
  if (mode === 'import') {
    for (const line of report.lines) {
      const sourceFile = line.provenance?.sourceFile;
      if (!sourceFile) fail('Imported source provenance is missing.');
      const actual = await realpath(path.resolve(root,sourceFile));
      if (!actual.startsWith(root + path.sep)) fail('Imported audio source escapes the project.');
      if (createHash('sha256').update(await readFile(actual)).digest('hex') !== line.sourceSha256) fail('Imported audio changed: rerun preparation before export.');
    }
  }
  if (timeline.audioSrc) {
    if (typeof timeline.audioSrc !== 'string' || path.isAbsolute(timeline.audioSrc)) fail('Audio source must be relative to public.');
    const publicRoot = path.join(root,'public');
    const audio = path.resolve(publicRoot,timeline.audioSrc);
    if (!audio.startsWith(publicRoot + path.sep)) fail('Audio source escapes public.');
    await access(audio);
    if (createHash('sha256').update(await readFile(audio)).digest('hex') !== report.audioSha256) fail('Prepared mix changed: rerun preparation before export.');
    const result = spawnSync('ffprobe',['-v','error','-show_entries','format=duration:stream=codec_type,sample_rate,channels','-of','json',audio],{encoding:'utf8'});
    if (result.error?.code === 'ENOENT') fail('ffprobe is missing. Install FFmpeg/FFprobe and rerun.');
    if (result.status !== 0) fail('Prepared audio cannot be read by ffprobe.');
    const info = JSON.parse(result.stdout);
    const stream = info.streams?.find(s => s.codec_type === 'audio');
    if (!stream || stream.sample_rate !== '48000' || stream.channels !== 2 || Math.abs(Number(info.format.duration) - timeline.durationSeconds) > .06) fail('Prepared mix must be 48kHz stereo and match the complete timeline.');
  } else if (timeline.narrated) fail('Narrated film has no real soundtrack.');
  console.log(`Film check passed: ${timeline.scenes.length} scenes, ${lines.length} captions, ${timeline.durationInFrames} frames; ${timeline.narrated ? 'real audio prepared (content review still required)' : 'no narration'}.`);
} catch (error) {
  console.error('Film check failed: ' + error.message);
  process.exitCode = 1;
}
