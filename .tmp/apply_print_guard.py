"""Apply print_guard wire-up to src/xragent/main.py (3 sites + 1 import)."""
from pathlib import Path
p = Path("src/xragent/main.py")
s = p.read_text(encoding="utf-8")
orig_lines = len(s.splitlines())
print(f"original: {len(s)} chars, {orig_lines} lines")

# 1. import: add print_guard between heartbeat and subprocess_utils
old_imp = "from .util.heartbeat import start_heartbeat_thread\nfrom .util.subprocess_utils import run_capture"
new_imp = "from .util.heartbeat import start_heartbeat_thread\nfrom .util.print_guard import print_guard\nfrom .util.subprocess_utils import run_capture"
assert s.count(old_imp) == 1, f"import anchor hits={s.count(old_imp)}"
s = s.replace(old_imp, new_imp)

# 2. push site (inside maybe_periodic_push)
old_push = (
    "        try:\n"
    "            ok, msg = sg.push()\n"
    "            if ok:\n"
    "                print(f\"[autonomous] pushed {n} commit(s) to origin/main\", flush=True)\n"
    "            else:\n"
    "                print(f\"[autonomous] push returned ok=False: {msg[:200]}\", flush=True)\n"
    "            last_push_ts = now\n"
    "        except Exception as e:\n"
    "            print(f\"[autonomous] push failed: {e}\", flush=True)"
)
new_push = (
    "        result = print_guard(\"push\", lambda: sg.push())\n"
    "        if result is not None:\n"
    "            ok, msg = result\n"
    "            if ok:\n"
    "                print(f\"[autonomous] pushed {n} commit(s) to origin/main\", flush=True)\n"
    "            else:\n"
    "                print(f\"[autonomous] push returned ok=False: {msg[:200]}\", flush=True)\n"
    "        last_push_ts = now"
)
assert s.count(old_push) == 1, f"push anchor hits={s.count(old_push)}"
s = s.replace(old_push, new_push)

# 3. task gen site (in main while loop)
old_task = (
    "            try:\n"
    "                task = next_task()\n"
    "            except Exception as e:\n"
    "                print(f\"[autonomous] task gen error: {e}; sleep 60s\", flush=True)\n"
    "                time.sleep(60)\n"
    "                continue"
)
new_task = (
    "            task = print_guard(\"task gen\", next_task)\n"
    "            if task is None:\n"
    "                time.sleep(60)\n"
    "                continue"
)
assert s.count(old_task) == 1, f"task anchor hits={s.count(old_task)}"
s = s.replace(old_task, new_task)

# 4. commit site (in main while loop)
old_commit = (
    "            try:\n"
    "                head = sg.add_all_and_commit(f\"autonomous: {task['title'][:60]} (round {rounds})\")\n"
    "                if head:\n"
    "                    print(f\"[autonomous] committed {head[:8]}\", flush=True)\n"
    "                    # \u7b2c\u4e00\u6b21 commit \u540e\u7acb\u5373 push\uff1b\u4e4b\u540e\u6bcf push_interval_minutes\n"
    "                    maybe_periodic_push(force=(last_push_ts == 0.0))\n"
    "            except Exception as e:\n"
    "                print(f\"[autonomous] commit failed: {e}\", flush=True)"
)
new_commit = (
    "            head = print_guard(\n"
    "                \"commit\",\n"
    "                lambda: sg.add_all_and_commit(f\"autonomous: {task['title'][:60]} (round {rounds})\"),\n"
    "            )\n"
    "            if head:\n"
    "                print(f\"[autonomous] committed {head[:8]}\", flush=True)\n"
    "                # \u7b2c\u4e00\u6b21 commit \u540e\u7acb\u5373 push\uff1b\u4e4b\u540e\u6bcf push_interval_minutes\n"
    "                maybe_periodic_push(force=(last_push_ts == 0.0))"
)
assert s.count(old_commit) == 1, f"commit anchor hits={s.count(old_commit)}"
s = s.replace(old_commit, new_commit)

new_lines = len(s.splitlines())
print(f"new:      {len(s)} chars, {new_lines} lines")
print(f"delta:    {new_lines - orig_lines:+d} lines")

# Sanity: import + 3 print_guard call sites present
assert s.count("print_guard(") == 3, s.count("print_guard(")
assert "from .util.print_guard import print_guard" in s

# Save for inspection before write_file to src/
Path(".tmp/main_v2.py").write_text(s, encoding="utf-8")
print("WROTE .tmp/main_v2.py")