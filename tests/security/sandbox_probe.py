# Attacks the running sandbox from inside. Pipe this after backend/app/sandbox_client.py into a container that
# mounts the job volume at /sandbox-jobs (see docs/operations/SANDBOX.md). Every attempt must fail.

ESCAPES = r'''
import os, pathlib, socket, subprocess, pytest

@pytest.mark.parametrize("host,port", [("1.1.1.1", 53), ("host.docker.internal", 11434), ("api", 8000), ("db", 5432)])
def test_no_network(host, port):
    with pytest.raises(OSError):
        socket.create_connection((host, port), timeout=2)

def test_only_loopback_at_most():
    names = [n for _, n in socket.if_nameindex()]
    assert set(names) <= {"lo"}

def test_runs_unprivileged_with_a_clean_environment():
    assert os.getuid() == 2000 and os.getgid() == 2000 and os.getgroups() == []
    assert not [k for k in os.environ if "AIDLC" in k or "KEY" in k or "SECRET" in k or "PASSWORD" in k]

@pytest.mark.parametrize("path", ["/jobs", "/jobs/in", "/jobs/out"])
def test_job_folder_is_out_of_reach(path):
    with pytest.raises(PermissionError):
        os.listdir(path)

def test_result_cannot_be_forged():
    with pytest.raises(PermissionError):
        pathlib.Path("/jobs/out/forged.json").write_text("{}")

@pytest.mark.parametrize("path", ["/opt/sandbox/runner.py", "/usr/bin/planted", "/etc/planted"])
def test_root_filesystem_is_read_only(path):
    with pytest.raises(OSError):
        open(path, "a").close()

def test_cannot_become_root():
    with pytest.raises(PermissionError):
        os.setuid(0)

def test_runner_memory_and_environment_are_private():
    with pytest.raises(PermissionError):
        open("/proc/1/environ").read()

def test_other_workspaces_are_hidden():
    with pytest.raises(PermissionError):
        os.listdir("/work")

def test_temp_cannot_run_programs():
    target = "/tmp/run-me.sh"
    with open(target, "w") as handle:
        handle.write("#!/bin/sh\necho hi\n")
    os.chmod(target, 0o700)
    with pytest.raises(PermissionError):
        subprocess.run([target], check=True)
'''

LEAVE_BEHIND = '''
import subprocess, sys
def test_start_a_detached_process():
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
'''

NOTHING_LEFT = '''
import os, pathlib
def test_earlier_processes_are_gone():
    mine, others = os.getpid(), []
    for entry in pathlib.Path("/proc").iterdir():
        if entry.name.isdigit() and int(entry.name) != mine:
            try:
                cmd = (entry / "cmdline").read_bytes()
                if entry.stat().st_uid == 2000 and b"time.sleep(300)" in cmd:
                    others.append(entry.name)
            except OSError:
                pass
    assert not others
'''

FORK_BOMB = '''
import os
def test_bomb():
    children = 0
    try:
        while children < 5000:
            if os.fork() == 0:
                import time; time.sleep(30); os._exit(0)
            children += 1
    except OSError:
        pass
    assert children < 200
'''

SPIN = "def test_forever():\n    while True:\n        pass\n"
NOISE = "def test_noise():\n    while True:\n        print('x' * 100000)\n"


def _py(name, body):
    return [{"path": name, "content": body}]


box = FolderSandbox("/sandbox-jobs", 240)
failures = []


def expect(label, ok, detail=""):
    print(("ok    " if ok else "FAIL  ") + label, flush=True)
    if not ok:
        failures.append(f"{label}: {detail}")


r = box.run(_py("test_escape.py", ESCAPES))
expect("every escape attempt fails", r["checks"]["unit_tests"]["passed"], r["checks"]["unit_tests"]["output"][-1500:])
box.run(_py("test_leave.py", LEAVE_BEHIND))
r = box.run(_py("test_after.py", NOTHING_LEFT))
expect("detached processes do not survive a job", r["checks"]["unit_tests"]["passed"], r["checks"]["unit_tests"]["output"][-500:])
r = box.run(_py("test_bomb.py", FORK_BOMB))
expect("process count is capped", r["checks"]["unit_tests"]["passed"], r["checks"]["unit_tests"]["output"][-500:])
r = box.run(_py("test_spin.py", SPIN))
expect("an endless test is stopped and fails", not r["checks"]["unit_tests"]["passed"], str(r["checks"]["unit_tests"])[:200])
r = box.run(_py("test_noise.py", NOISE))
expect("endless output is capped", not r["checks"]["unit_tests"]["passed"] and len(r["checks"]["unit_tests"]["output"]) <= 9000)
for path in ("../evil.py", "/etc/evil.py", "a/../../evil.py", ".hidden.py", "run.sh"):
    r = box.run(_py(path, "x = 1\n"))
    expect(f"rejected path {path}", not r["checks"]["build"]["passed"] and r["language"] is None)
good = [{"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"},
        {"path": "test_calc.py", "content": "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"}]
r = box.run(good)
expect("a real Python project passes", r["checks"]["build"]["passed"] and r["checks"]["unit_tests"]["passed"], str(r)[:400])
bad = [good[0], {"path": "test_calc.py", "content": "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 6\n"}]
r = box.run(bad)
expect("a failing test really fails", not r["checks"]["unit_tests"]["passed"])
r = box.run([{"path": "broken.py", "content": "def nope(:\n"}, good[1]])
expect("broken code fails the build", not r["checks"]["build"]["passed"])
js = [{"path": "sum.js", "content": "exports.sum = (a, b) => a + b;\n"},
      {"path": "sum.test.js", "content": "const t = require('node:test'), a = require('node:assert'), {sum} = require('./sum');\n"
                                         "t.test('adds', () => a.strictEqual(sum(2, 3), 5));\n"}]
r = box.run(js)
expect("a real JavaScript project passes", r["checks"]["build"]["passed"] and r["checks"]["unit_tests"]["passed"], str(r)[:400])
print("PROBE FAILURES:", failures)
raise SystemExit(1 if failures else 0)
