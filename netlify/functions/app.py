import os
import sys
import importlib.util
from urllib.parse import urlparse

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
    """Netlify Functions Serverless WSGI entrypoint for Flask with automatic path normalization."""
    headers = event.get('headers') or {}
    
    # 1. Look for original client path forwarded by Netlify Edge proxy
    client_path = None
    for header_name in ['x-original-url', 'x-rewrite-url', 'x-forwarded-uri', 'x-nf-original-path']:
        val = headers.get(header_name) or headers.get(header_name.lower())
        if val:
            client_path = urlparse(val).path
            break
            
    if not client_path and event.get('rawUrl'):
        try:
            client_path = urlparse(event['rawUrl']).path
        except Exception:
            pass

    path = event.get('path', '')
    if client_path and not client_path.startswith('/.netlify/functions/'):
        path = client_path
    elif path.startswith('/.netlify/functions/app'):
        subpath = path[len('/.netlify/functions/app'):]
        path = subpath if subpath else '/'

    event['path'] = path

    return serverless_wsgi.handle_request(flask_app, event, context)
