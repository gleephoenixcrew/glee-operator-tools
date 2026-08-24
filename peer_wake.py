#!/usr/bin/env python3
"""GLEE Peer Wake v0.3 public facade.

Peer ingress can only queue authenticated evidence. Wake authority requires a
separate locally signed authorization carrying a locally chosen compute lease.
"""
from peer_wake_models import *
from peer_wake_storage import *
from peer_wake_control import *
from peer_wake_cli import build_parser, main

if __name__ == "__main__":
    raise SystemExit(main())
