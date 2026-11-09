"""Start the app: python -m webapp  (then open http://127.0.0.1:8765)"""

import os
import threading
import webbrowser

import uvicorn


def main() -> None:
    port = int(os.environ.get("CASHFLOW_PORT", "8765"))
    url = f"http://127.0.0.1:{port}"
    print(f"Cashflow Planner running at {url}  (press Ctrl+C to stop)")
    if not os.environ.get("CASHFLOW_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run("webapp.app:app", host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
