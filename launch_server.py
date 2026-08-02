"""Launch the MCP server as a detached process, preserving the current environment."""
import os
import subprocess
import sys
import time

server_dir = os.path.dirname(os.path.abspath(__file__))
log_path = os.path.join(server_dir, "server_run.log")
env = os.environ.copy()
env["WORKSPACE_ROOT"] = "/home/userland/OllamaDev"

# If an Ollama API key is stashed in a temp file, load it and point at the cloud host.
key_file = "/tmp/ollama_api_key"
if os.path.exists(key_file) and not env.get("OLLAMA_API_KEY"):
    with open(key_file) as f:
        env["OLLAMA_API_KEY"] = f.read().strip()
    env.setdefault("OLLAMA_URL", "https://ollama.com")

proc = subprocess.Popen(
    [sys.executable, "server.py"],
    cwd=server_dir,
    env=env,
    stdout=open(log_path, "w"),
    stderr=subprocess.STDOUT,
    start_new_session=True,
)
print(f"server pid: {proc.pid}, log: {log_path}")
time.sleep(2)
print("done")
