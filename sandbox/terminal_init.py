"""Prepares a terminal session's container (Phase 2d), then keeps it alive for the session's maximum length.

Starts as root with only CHOWN, SETUID and SETGID: hands /repo and /work to the unprivileged user, drops to it for
good, and checks out the chosen branch into /work/project (a working copy: nothing here is pushed back; commits are
made from the IDE's editor). The shell the person types into is started separately by the executor, as uid 2000. The
container has no network.
"""

import os
import re
import subprocess
import sys

CODE_UID = 2000
REF = re.compile(r"^(?!.*\.\.)(?!.*//)(?!/)(?!.*\.lock$)[A-Za-z0-9][A-Za-z0-9._/\-]{0,99}$")


def main() -> None:
    branch, seconds = sys.argv[1], int(sys.argv[2])
    if not REF.match(branch):
        raise SystemExit("invalid branch")
    for root, folders, files in os.walk("/repo"):
        for name in [*folders, *files]:
            os.lchown(os.path.join(root, name), CODE_UID, CODE_UID)
        os.lchown(root, CODE_UID, CODE_UID)
    os.chown("/work", CODE_UID, CODE_UID)
    os.setgroups([])
    os.setgid(CODE_UID)
    os.setuid(CODE_UID)
    if os.getuid() != CODE_UID:
        raise SystemExit("could not drop privileges")
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/work", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "protocol.file.allow=always", "clone", "--quiet",
                    "--branch", branch, "/repo/project.git", "/work/project"], env=env, check=True, timeout=60)
    with open("/work/.ready", "w") as ready:  # the executor waits for this before starting the shell
        ready.write("ok")
    os.execvp("sleep", ["sleep", str(seconds)])


if __name__ == "__main__":
    main()
