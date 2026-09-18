#!/usr/bin/env python3
"""Run one benchmark-neutral RDF campaign."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_executor.rdf_campaign import CampaignSpecification, RdfCampaign

def parse_arguments(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', type=Path, required=True)
    parser.add_argument('--declaration', type=Path, required=True)
    parser.add_argument('--benchmark-root', type=Path)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--repetitions', type=int, default=3)
    parser.add_argument('--system', action='append', default=[])
    parser.add_argument('--system-limit-s', type=int, default=7200)
    parser.add_argument('--campaign-id')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    return parser.parse_args(argv)

def main(argv=None):
    arguments = parse_arguments(argv)
    here = Path(__file__).resolve().parent
    specification = CampaignSpecification(
        arguments.scenario, arguments.declaration, arguments.manifest,
        arguments.benchmark_root, arguments.repetitions, tuple(arguments.system),
        arguments.system_limit_s, arguments.campaign_id,
    )
    campaign = RdfCampaign(
        specification, here / 'run_rdf_experiment_matrix.py',
        here / 'summarize_rdf_experiment.py', here / 'analyze_rdf_inter_runs.py',
    )
    return 0 if campaign.run(arguments.resume, arguments.retry_failed)['complete'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
