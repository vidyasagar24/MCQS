#   & "C:\Users\acer\anaconda3\python.exe" run.py
import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ['true', '1', 'yes']
    print("\n" + "=" * 70)
    print(" MATHQUIZ – ONLINE MATHEMATICS EXAMINATION SYSTEM")
    print(" Assessment Management & Real-Time Proctoring Portal v1.0")
    print("=" * 70)
    print(f" * Server running on: http://127.0.0.1:{port}/")
    print(f" * Student Portal:   http://127.0.0.1:{port}/mathquiz/student")
    print(f" * Admin Console:    http://127.0.0.1:{port}/mathquiz/admin")
    print(" * Admin Login:       admin / Admin@123")
    print("=" * 70 + "\n")
    app.run(host='0.0.0.0', port=port, debug=debug)
