#!/usr/bin/env python3
"""Launch the generic RDF campaign for a benchmark-owned BSBM declaration."""
from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

KROWN = Path('/users/u0182905/KROWN')
BENCHMARKS = Path('/users/u0182905/benchmarks')
PROFILES = {
    '1k-smoke': ('BSBM/experiments/explore-1k-smoke.json', 'benchmark-integration/bsbm-10k', 'manifests/bsbm-1k-smoke.json'),
    '100k-full': ('BSBM/experiments/explore-100k-full.json', 'benchmark-integration/bsbm-100k', 'manifests/bsbm.json'),
}

def parse_arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('profile', choices=sorted(PROFILES))
    parser.add_argument('--campaign-id', required=True)
    parser.add_argument('--system', action='append', default=[])
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--system-limit-s', type=int, default=7200)
    parser.add_argument('--dry-run', action='store_true')
    return parser.parse_args(argv)

def command(arguments):
    declaration, scenario, manifest = PROFILES[arguments.profile]
    repetitions = 1 if arguments.profile == '1k-smoke' else 3
    result = [
        sys.executable, str(KROWN / 'execution-framework/run_rdf_campaign.py'),
        '--scenario', str(KROWN / scenario),
        '--declaration', str(BENCHMARKS / declaration),
        '--benchmark-root', str(BENCHMARKS / 'BSBM'),
        '--manifest', manifest,
        '--repetitions', str(repetitions),
        '--system-limit-s', str(arguments.system_limit_s),
        '--campaign-id', arguments.campaign_id,
    ]
    for system in arguments.system:
        result.extend(['--system', system])
    if arguments.resume:
        result.append('--resume')
    if arguments.retry_failed:
        result.append('--retry-failed')
    return result

def main(argv=None):
    arguments = parse_arguments(argv)
    selected = command(arguments)
    print(' '.join(selected), flush=True)
    if arguments.dry_run:
        return 0
    return subprocess.run(selected, cwd=KROWN, check=False).returncode

if __name__ == '__main__':
    raise SystemExit(main())
