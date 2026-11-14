import subprocess
import sys

from core.config import settings


def main() -> None:
    print(f"[launcher] worker.count={settings.worker_count}個のワーカーを起動します")
    processes = [
        subprocess.Popen([sys.executable, "-u", "-m", "worker.main"])
        for _ in range(settings.worker_count)
    ]
    try:
        for process in processes:
            process.wait()
    except KeyboardInterrupt:
        for process in processes:
            process.terminate()


if __name__ == "__main__":
    main()
