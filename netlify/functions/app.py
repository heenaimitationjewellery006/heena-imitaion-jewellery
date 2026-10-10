import os
import sys
import importlib.util

# Determine root directory containing app.py
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Dynamically import root app.py to avoid module name collision
root_app_path = os.path.join(ROOT_DIR, "app.py")
spec = importlib.util.spec_from_file_location("main_app", root_app_path)
main_app = importlib.util.module_from_spec(spec)
sys.modules["main_app"] = main_app
spec.loader.exec_module(main_app)

flask_app = main_app.app
init_db = getattr(main_app, "init_db", None)

try:
    if callable(init_db):
        init_db()
except Exception as init_err:
    print("Netlify function init_db note:", init_err)

import serverless_wsgi

def handler(event, context):
    """Netlify Functions Serverless WSGI entrypoint for Flask."""
    return serverless_wsgi.handle_request(flask_app, event, context)
