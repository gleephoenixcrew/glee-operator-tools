#!/usr/bin/env python3
"""Compatibility entrypoint for the GLEE Peer Wake Protocol v0.3 candidate."""
from peer_wake_v03 import *  # noqa: F401,F403

if __name__ == "__main__":
    raise SystemExit(main())
