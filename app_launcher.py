"""
Testo 174T - Masaustu launcher.
PyInstaller --noconsole ile derlenir; terminal penceresi acilmaz.
"""
import sys
import os
import threading
import webbrowser
import time

# knowledge_base ve diger kullanici dosyalari exe yaninda olmali
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from app import app


def _open_browser():
    time.sleep(2)
    webbrowser.open('http://127.0.0.1:5000')


if __name__ == '__main__':
    threading.Thread(target=_open_browser, daemon=True).start()
    app.run(host='127.0.0.1', port=5000, debug=False, use_reloader=False)
