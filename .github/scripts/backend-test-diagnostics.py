"""Expose unittest failure tracebacks as annotations without hiding failures."""
import re
import subprocess
import sys
from pathlib import Path


def annotation(text):
    return text.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def main():
    result = subprocess.run([sys.executable, '-X', 'utf8', '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = result.stdout.decode('utf-8', errors='strict')
    folder = Path('test-results/ci')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'backend.log').write_text(output, encoding='utf-8')
    print(output, end='')
    if result.returncode:
        failures = re.findall(r'^={20,}\r?\n((?:ERROR|FAIL):.*?)(?=^={20,}|^-{20,}\r?\nRan |\Z)',
                              output, flags=re.MULTILINE | re.DOTALL)
        for failure in failures or [output[-16000:]]:
            print('::error title=Backend regression failure::' + annotation(failure[:16000]))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
