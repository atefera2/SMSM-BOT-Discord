"""
Loads bot.py as a module without connecting to Discord.

bot.py builds its Bot object and reads config.json at import time, which is fine
offline. State is redirected to a temp dir so running tests never touches a live
state.json.
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def bot():
    os.environ.setdefault("SMSM_STATE_DIR", tempfile.mkdtemp(prefix="smsm-test-"))
    os.environ.setdefault("DISCORD_TOKEN", "test-token-not-used")
    spec = importlib.util.spec_from_file_location("smsm_bot", REPO / "bot.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["smsm_bot"] = module
    spec.loader.exec_module(module)
    return module
