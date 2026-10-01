from __future__ import annotations
import subprocess
from unittest.mock import call, patch
from bench_executor.rdf_campaign import terminate_user_scope

def test_scope_stops_after_sigint():
    with patch("bench_executor.rdf_campaign.user_scope_active",side_effect=[True,False,False,False]), patch("bench_executor.rdf_campaign.subprocess.run") as run:
        value=terminate_user_scope("unit",grace_s=0)
    assert value["signals"]==["SIGINT"] and value["terminated"]
    assert call(["systemctl","--user","kill","--kill-whom=all","--signal=SIGINT","unit"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False) in run.call_args_list

def test_scope_escalates_and_detects_remaining_processes():
    with patch("bench_executor.rdf_campaign.user_scope_active",side_effect=[True,True,True,True,True,True,True]), patch("bench_executor.rdf_campaign.subprocess.run"), patch("bench_executor.rdf_campaign.time.monotonic",side_effect=[0,1,0,1,0,1]):
        value=terminate_user_scope("unit",grace_s=0)
    assert value["signals"]==["SIGINT","SIGTERM","SIGKILL"]
    assert value["remaining_active"] and not value["terminated"]

def test_inactive_scope_only_resets_unit():
    with patch("bench_executor.rdf_campaign.user_scope_active",side_effect=[False,False]), patch("bench_executor.rdf_campaign.subprocess.run") as run:
        value=terminate_user_scope("unit",grace_s=0)
    assert value["signals"]==[] and value["terminated"] and run.call_count==1
