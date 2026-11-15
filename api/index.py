import os
import sys
from urllib.parse import parse_qs, urlencode
from werkzeug.middleware.proxy_fix import ProxyFix

# Add project root directory to sys.path for serverless execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

# Vercel serverless function entrypoint (must stay top-level for @vercel/python AST detection)
app = create_app()

class VercelPathFixer:
    """WSGI middleware ensuring proper PATH_INFO routing when deployed behind Vercel edge rewrites."""
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app

    def __call__(self, environ, start_response):
        qs = environ.get('QUERY_STRING', '')
        params = parse_qs(qs, keep_blank_values=True)

        # Check for forwarded route param from Vercel rewrite
        route_key = None
        for key in ('__route', '__vercel_route', 'path'):
            if key in params:
                route_key = key
                break

        if route_key:
            raw_path = params.pop(route_key)[0]
            if raw_path:
                environ['PATH_INFO'] = '/' + raw_path.lstrip('/')
            else:
                environ['PATH_INFO'] = '/'
            # Reconstruct clean QUERY_STRING without internal route param
            clean_pairs = []
            for k, vals in params.items():
                for v in vals:
                    clean_pairs.append((k, v))
            environ['QUERY_STRING'] = urlencode(clean_pairs)
        elif environ.get('PATH_INFO') in ('/api/index', '/api/index.py', '/api'):
            environ['PATH_INFO'] = '/'

        return self.wsgi_app(environ, start_response)

# Trust reverse-proxy headers from Vercel (https, correct client host, etc.)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.wsgi_app = VercelPathFixer(app.wsgi_app)
