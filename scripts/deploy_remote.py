"""服务器部署辅助脚本:通过 paramiko 执行远程操作。

用法:
    python scripts/deploy_remote.py <command>

凭据从环境变量或本地文件读,**绝不写进源码**:

    # 方式一:环境变量
    export WLCB_HOST=1.2.3.4 WLCB_USER=root WLCB_PASSWORD=...

    # 方式二:项目根目录的 deploy_creds.env(已在 .gitignore 中)
    WLCB_HOST=1.2.3.4
    WLCB_USER=root
    WLCB_PASSWORD=...

为什么改成这样:这个脚本原来把服务器 root 密码硬编码在第 15 行,
而仓库是公开的——等于把服务器密码公开了。凭据一旦进过版本库,
就算后续删掉,历史里还在,必须换密码而不是删代码。
"""
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import paramiko

BASE = Path(__file__).resolve().parent.parent
CRED_FILE = BASE / "deploy_creds.env"


def load_creds() -> tuple:
    """返回 (host, user, password)。环境变量优先,其次是 deploy_creds.env。"""
    creds = {
        "host": os.environ.get("WLCB_HOST", "").strip(),
        "user": os.environ.get("WLCB_USER", "").strip(),
        "password": os.environ.get("WLCB_PASSWORD", "").strip(),
    }
    if not all(creds.values()) and CRED_FILE.exists():
        for line in CRED_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip().lower()
            # 文件里写的是 WLCB_HOST 这种带前缀的键,映射到 host/user/password
            if key.startswith("wlcb_"):
                key = key[len("wlcb_"):]
            if key in creds and not creds[key]:
                creds[key] = v.strip()

    missing = [k for k, v in creds.items() if not v]
    if missing:
        raise SystemExit(
            "缺少部署凭据:" + ", ".join(missing) + "\n"
            "请设置环境变量 WLCB_HOST / WLCB_USER / WLCB_PASSWORD,\n"
            f"或写入 {CRED_FILE.name}（该文件已在 .gitignore 中,不会提交）。"
        )
    return creds["host"], creds["user"], creds["password"]


def conn():
    host, user, password = load_creds()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=20)
    return ssh


def run(ssh, cmd, timeout=60, quiet=False):
    _, out, err = ssh.exec_command(cmd, timeout=timeout)
    o = out.read().decode("utf-8", errors="replace")
    e = err.read().decode("utf-8", errors="replace")
    if not quiet:
        if o.strip():
            print(o.strip())
        if e.strip():
            print("[stderr]", e.strip()[:300])
    return o


def run_long(ssh, cmd, logname, wait=900):
    """在完全分离的会话里执行长命令,轮询日志。

    关键:用 setsid + </dev/null + 重定向把所有 stdio 都断开,
    paramiko 才不会因为管道未关闭而阻塞读。
    """
    script = f"/tmp/{logname}.sh"
    sftp = ssh.open_sftp()
    with sftp.open(script, "w") as f:
        f.write("#!/bin/bash\n" + cmd + "\n")
    sftp.close()

    # ⚠️ 三处重定向缺一不可:stdin/stdout/stderr 全断,进程组独立
    launcher = (
        f"chmod +x {script} && "
        f"setsid bash -c '{script} </dev/null >/tmp/{logname}.log 2>&1' "
        f"</dev/null >/dev/null 2>&1 & "
        f"disown; sleep 2; echo LAUNCHED"
    )
    ssh.exec_command(launcher, timeout=15)

    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(15)
        flag = run(ssh, f"pgrep -f '{logname}.sh' >/dev/null && echo running || echo done",
                   timeout=20, quiet=True).strip()
        if flag == "done":
            break
    return run(ssh, f"tail -25 /tmp/{logname}.log", timeout=40)


def run_bg(ssh, cmd, logname, wait=600):
    return run_long(ssh, cmd, logname, wait=wait)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    ssh = conn()
    try:
        if action == "check":
            print("=== pip ===")
            run(ssh, "pip3 --version 2>&1 | head -1 || echo 'NOT INSTALLED'")
            print("\n=== 依赖 ===")
            run(ssh, "cd /opt/wlcb && python3 -c \"import streamlit,neo4j,numpy,pandas,requests;print('ALL_DEPS_OK')\" 2>&1 | tail -3")
            print("\n=== pip 进程 ===")
            run(ssh, "pgrep -af pip3 | head -3 || echo 'no pip running'")

        elif action == "install":
            print("=== 后台安装依赖 ===")
            r = run_bg(
                ssh,
                "cd /opt/wlcb\n"
                "pip3 install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/\n"
                "python3 -c \"import streamlit,neo4j,numpy,pandas,requests;print('ALL_DEPS_OK')\"\n",
                "pipinstall",
                wait=600,
            )
            print(r[-800:])

        elif action == "start":
            print("=== 启动 Streamlit ===")
            r = run_bg(
                ssh,
                "cd /opt/wlcb\n"
                "streamlit run app.py --server.port 8501 --server.address 0.0.0.0 "
                "--server.headless true --browser.gatherUsageStats false\n",
                "streamlit",
                wait=60,
            )
            print(r[-500:])

        elif action == "raw":
            run(ssh, sys.argv[2], timeout=120)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
