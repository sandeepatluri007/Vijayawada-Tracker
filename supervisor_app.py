"""Supervisor app — entry file for the second Streamlit Cloud app.

It runs Vja_app.py in supervisor mode: each supervisor logs in with their own
PIN and sees only their own locations, with no rupee figures. Keep this file
next to Vja_app.py in the repo; all changes go into Vja_app.py, and both apps
pick them up.
"""
import os

os.environ["VJA_APP_MODE"] = "supervisor"
_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Vja_app.py")
with open(_path, encoding="utf-8") as _f:
    exec(compile(_f.read(), _path, "exec"))
