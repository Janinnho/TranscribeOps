import os

from app import create_app

app = create_app()

if __name__ == '__main__':
    # Dev server only — production runs gunicorn (run:app). Debug mode
    # (Werkzeug debugger = RCE) must be opted into explicitly.
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, host=os.environ.get('FLASK_RUN_HOST', '127.0.0.1'), port=5000)
