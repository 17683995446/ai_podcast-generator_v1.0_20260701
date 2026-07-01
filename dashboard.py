"""GitHub 播客工具 · Web 仪表盘 · 启动入口"""
import os
from dashboard import create_app
from dashboard.config import EPISODES_DIR, SCRIPTS_DIR

app = create_app()

if __name__ == "__main__":
    os.makedirs(str(EPISODES_DIR), exist_ok=True)
    os.makedirs(str(SCRIPTS_DIR), exist_ok=True)
    print("=" * 50)
    print("  GitHub 播客工具 · Web 仪表盘")
    print("  访问: http://localhost:5000")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
