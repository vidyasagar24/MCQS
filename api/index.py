import os
import sys

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
        if 'debug=1' in environ.get('QUERY_STRING', ''):
            status = '200 OK'
            headers = [('Content-Type', 'application/json')]
            import json
            data = {
                'PATH_INFO': environ.get('PATH_INFO'),
                'SCRIPT_NAME': environ.get('SCRIPT_NAME'),
                'RAW_URI': environ.get('RAW_URI'),
                'REQUEST_URI': environ.get('REQUEST_URI'),
                'QUERY_STRING': environ.get('QUERY_STRING'),
                'HTTP_HEADERS': {k: v for k, v in environ.items() if k.startswith('HTTP_')}
            }
            start_response(status, headers)
            return [json.dumps(data, indent=2).encode('utf-8')]

        matched = environ.get('HTTP_X_MATCHED_PATH')
        path_info = environ.get('PATH_INFO', '')

        # If Vercel provided the original route in HTTP_X_MATCHED_PATH
        if matched and matched not in ('/api/index', '/api/index.py', '/api'):
            environ['PATH_INFO'] = matched
        elif path_info.startswith('/api/index/'):
            environ['PATH_INFO'] = path_info[len('/api/index'):]
        elif path_info.startswith('/api/index.py/'):
            environ['PATH_INFO'] = path_info[len('/api/index.py'):]
        elif path_info in ('/api/index', '/api/index.py', '/api', ''):
            environ['PATH_INFO'] = '/'

        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathFixer(app.wsgi_app)
