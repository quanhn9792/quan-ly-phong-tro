import os

from src.web import create_app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    try:
        from waitress import serve
    except ImportError:  # chưa cài waitress: dùng server dev của Flask (chỉ nên dùng trên máy)
        app.run(host=host, port=port, debug=False)
    else:
        print(f"Dang chay tai http://{host}:{port}")
        serve(app, host=host, port=port, threads=8)
