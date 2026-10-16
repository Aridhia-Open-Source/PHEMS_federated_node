"""Container entry point: the API under waitress plus the sync timer loop in a thread."""
import threading

from waitress import serve

from app import create_app
from app.sync import run_forever


def main():
    app = create_app()
    threading.Thread(target=run_forever, args=(app,), daemon=True, name='sync-timer').start()
    serve(app, host='0.0.0.0', port=5000)


if __name__ == '__main__':
    main()
