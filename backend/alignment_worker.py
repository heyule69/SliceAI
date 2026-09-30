"""Isolated pinned Qwen3 forced aligner; local weights only, JSONL progress."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path


def verify_weights(model):
    from fine_alignment import model_identity
    model_identity(model)
    manifest = json.loads((model / 'manifest.json').read_text(encoding='utf-8', errors='strict'))
    for name, info in manifest['files'].items():
        path = (model / name).resolve()
        if path.parent != model.resolve():
            raise ValueError('Unsafe model file.')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while block := stream.read(1024*1024):
                digest.update(block)
        if digest.hexdigest() != info['sha256']:
            raise ValueError('Alignment model checksum mismatch.')


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def run(args):
    # Must be set before HuggingFace imports. Processor loading is offline too.
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
    import importlib.metadata
    for name, expected in (('qwen-asr', '0.0.6'), ('transformers', '4.57.6'),
                           ('torch', '2.6.0+cpu'), ('safetensors', '0.8.0')):
        if importlib.metadata.version(name) != expected:
            raise ValueError('Alignment runtime version differs from the pinned CPU environment: ' + name)
    emit({'event': 'loading', 'stage': 'verify_assets'})
    model = Path(args.model).resolve(); verify_weights(model)
    jobs = [json.loads(line) for line in Path(args.requests).read_text(encoding='utf-8', errors='strict').splitlines() if line.strip()]
    if not 1 <= len(jobs) <= 500:
        raise ValueError('Invalid alignment batch size.')
    emit({'event': 'loading', 'stage': 'import_torch'})
    import torch
    emit({'event': 'loading', 'stage': 'torch_ready'})
    torch.set_num_threads(max(1, min(4, args.threads)))
    torch.set_num_interop_threads(1)
    import soundfile as sf
    # Chinese alignment does not use the Japanese tokenizer. Preserve module
    # metadata during introspection; LazyLoader eagerly executes nagisa when
    # frozen PyTorch scans __file__ while registering its operators.
    # Actual tokenizer attributes still load the original package.
    import importlib.util
    if 'nagisa' not in sys.modules:
        import types
        spec = importlib.util.find_spec('nagisa')
        deferred = types.ModuleType('nagisa')
        deferred.__file__ = spec.origin
        deferred.__spec__ = spec
        deferred.__loader__ = spec.loader
        deferred.__package__ = 'nagisa'
        deferred.__path__ = spec.submodule_search_locations
        def load_attribute(name):
            if name.startswith('__'):
                raise AttributeError(name)
            module = importlib.util.module_from_spec(spec)
            sys.modules['nagisa'] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                sys.modules['nagisa'] = deferred
                raise
            return getattr(module, name)
        deferred.__getattr__ = load_attribute
        sys.modules['nagisa'] = deferred
    emit({'event': 'loading', 'stage': 'import_qwen'})
    from qwen_asr import Qwen3ForcedAligner
    # Windows/PyTorch can fault while slicing mmap-backed safetensors. Use the
    # upstream safetensors pread backend for this isolated CPU loader, retaining
    # the same verified weights. Transformers does not expose that knob yet.
    import functools
    import transformers.modeling_utils as modeling_utils
    modeling_utils.safe_open = functools.partial(modeling_utils.safe_open, backend='pread')
    emit({'event': 'loading', 'stage': 'load_model'})
    started = time.monotonic()
    aligner = Qwen3ForcedAligner.from_pretrained(str(model), dtype=torch.bfloat16,
                                                device_map='cpu', local_files_only=True,
                                                low_cpu_mem_usage=True)
    emit({'event': 'ready', 'load_seconds': time.monotonic()-started,
          'threads': torch.get_num_threads(), 'dtype': 'bfloat16', 'loader': 'safetensors-pread'})
    for job in jobs:
        started = time.monotonic()
        try:
            text = job['text']; start = float(job['start']); end = float(job['end'])
            if not isinstance(text, str) or not 1 <= len(text) <= 1500 or not 0 < end-start <= 32:
                raise ValueError('Invalid short alignment window.')
            samples, rate = sf.read(job['wav'], dtype='float32')
            if rate != 16000 or samples.ndim != 1 or abs(len(samples)/rate-(end-start)) > .01:
                raise ValueError('Alignment audio clock mismatch.')
            output = aligner.align(audio=(samples, rate), text=text, language=job.get('language', 'Chinese'))[0]
            words = [{'text': item.text, 'start': start + item.start_time,
                      'end': start + item.end_time} for item in output]
            emit({'event': 'alignment', 'id': job['id'], 'words': words,
                  'seconds': time.monotonic()-started})
        except Exception as exc:
            emit({'event': 'alignment', 'id': job.get('id'), 'error': str(exc)[:200]})


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True)
    parser.add_argument('--requests', required=True)
    parser.add_argument('--threads', type=int, default=2)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
