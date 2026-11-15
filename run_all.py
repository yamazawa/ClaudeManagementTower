import os
import subprocess
import sys


def main() -> None:
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")

    print("[run_all] サーバーとワーカーを起動します")
    processes = [
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            env=env,
        ),
        subprocess.Popen([sys.executable, "-u", "-m", "worker.launcher"], env=env),
    ]
    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()


if __name__ == "__main__":
    main()
