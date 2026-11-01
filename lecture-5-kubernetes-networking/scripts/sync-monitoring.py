"""Reuse the Lab 3 CR -> existing Prometheus/Grafana release adapter."""
from pathlib import Path
import runpy
import sys

source = Path(__file__).resolve().parents[2] / 'lecture-3-kubernetes-control-plane/scripts'
sys.path.insert(0, str(source))
runpy.run_path(str(source / 'sync-monitoring.py'), run_name='__main__')
