#!/usr/bin/env python3
"""Compatibility test entrypoint for the v0.3 candidate suite."""
import unittest
from test_peer_wake_v03 import *  # noqa: F401,F403

if __name__ == "__main__":
    unittest.main(verbosity=2)
