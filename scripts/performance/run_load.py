"""Run k6 with per-second process CPU sampling (one core = 100 percent)."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def process_ticks(master_pid):
    """Read CPU ticks for the gunicorn family and all local Postgres processes."""
    processes = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            name = stat[stat.index("(") + 1 : stat.rindex(")")]
            fields = stat[stat.rindex(")") + 2 :].split()
            processes[int(entry.name)] = (
                name,
                int(fields[1]),
                int(fields[11]) + int(fields[12]),
            )
        except (OSError, ValueError):
            continue
    return {
        pid: ("postgres" if name == "postgres" else "gunicorn", ticks)
        for pid, (name, parent, ticks) in processes.items()
        if name == "postgres" or pid == master_pid or parent == master_pid
    }


def main():
    """Execute one bounded scenario and persist CPU samples and its exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("script")
    parser.add_argument("--master-pid", type=int, required=True)
    args = parser.parse_args()
    output = Path("docs/development/performance-results")
    output.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, BASE_URL="http://127.0.0.1:8020")
    environment["SUMMARY_PATH"] = str(output / f"{args.label}-summary.json")
    command = ["/home/ubuntu/.local/bin/k6", "run", "--quiet", args.script]
    samples = []
    previous = process_ticks(args.master_pid)
    previous_time = time.monotonic()
    with (output / f"{args.label}.log").open("w") as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=log)
        while process.poll() is None:
            time.sleep(1)
            now = time.monotonic()
            current = process_ticks(args.master_pid)
            cpu = {"gunicorn": 0.0, "postgres": 0.0}
            for pid, (kind, ticks) in current.items():
                if pid in previous:
                    cpu[kind] += (
                        (ticks - previous[pid][1])
                        / os.sysconf("SC_CLK_TCK")
                        / (now - previous_time)
                        * 100
                    )
            cpu["load_1m"] = os.getloadavg()[0]
            samples.append(cpu)
            previous, previous_time = current, now
    result = {"exit_code": process.returncode, "samples": samples}
    (output / f"{args.label}-cpu.json").write_text(json.dumps(result, indent=2))
    print(f"{args.label}: k6 exit={process.returncode}; CPU samples={len(samples)}")
    raise SystemExit(process.returncode)


if __name__ == "__main__":
    main()
