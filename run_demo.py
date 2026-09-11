"""一键启动网页 Demo(在 PyCharm 里直接右键 Run 这个文件即可)。

等价于命令行: streamlit run app.py --server.port 8510
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

if __name__ == "__main__":
    print("启动 Streamlit,浏览器打开 http://localhost:8510")
    print("(按 Ctrl+C 停止)")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
         "--server.port", "8510", "--browser.gatherUsageStats", "false"],
        cwd=ROOT,
    )
