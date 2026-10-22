#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Verify every mode of a packaged ARM release on the real EYESY GPU.

tools/scene_verify.py runs on desktop software GL and cannot see failures that
only the Broadcom VC4 (GLES2 via Mesa) produces. This tool runs each mode through
tools/headless_test.py execute() (one engine launch per mode, offscreen, on the
device GPU, live instrument untouched) and classifies the retrieved evidence:

  setup_error  mode_errors > 0, error/shader_warning text, or the engine run failed
  gpu_compile  Mesa/VC4 compiler failure lines in engine.log, e.g.
               "Failed to register allocate" (draw silently does nothing and the
               engine reports no error)
  black / flat final grab mean luma or stddev below thresholds (scene_verify defaults)
  over_budget  experiment p50_ms above --budget-ms (default 33.3, tier C)
  pass         none of the above

A mode can have several findings. Exit status: 0 all pass; 1 any hard failure
(setup_error, gpu_compile, black, flat, or no result); 2 only over_budget
findings (1 if --fail-on-budget). Each mode costs one upload + engine launch:
roughly 20-40 s on the CM3+ for 180 frames.

Usage:
  device_verify.py ARCHIVE --host H --clone-id ID --output DIR [--mode M ...]
"""

import argparse
import contextlib
import io
import datetime
import json
import re
import sys
import time
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Lines that mean the GPU compiler rejected a shader even if the engine says nothing.
GPU_FAILURE = re.compile(
    r"Failed to register allocate"
    r"|Failed to compile (?:vertex|fragment|shader)"
    r"|(?:vc4|v3d)[^\n]*(?:compile|compiler)[^\n]*(?:fail|error)"
    r"|Failed to (?:link|assemble)"
    r"|(?:out of|ran out of) (?:registers|temporaries)",
    re.IGNORECASE,
)


def gpu_failures(log_text):
    """Distinct (first line of each) GPU compiler failure lines in engine.log."""
    found = []
    for line in log_text.splitlines():
        line = line.strip()
        if GPU_FAILURE.search(line) and line not in found:
            found.append(line)
    return found


def grab_stats(path):
    stat = ImageStat.Stat(Image.open(path).convert("L"))
    return {"mean": round(stat.mean[0], 2), "stddev": round(stat.stddev[0], 2)}


def classify(experiment, log_text, grab, args):
    """Pure classification. experiment: parsed experiment.json (or None), grab:
    {mean, stddev} of the final frame (or None). Returns (findings, detail)."""
    findings = []

    def add(kind, message):
        findings.append({"kind": kind, "message": message})

    final = (experiment or {}).get("final") or {}
    if experiment is None:
        add("setup_error", "no experiment.json retrieved")
    else:
        if final.get("mode_errors", 0) > 0:
            add("setup_error", f"mode_errors={final['mode_errors']}")
        for key in ("error", "shader_warning"):
            if final.get(key):
                add("setup_error", f"{key}: {final[key]}")
        if experiment.get("timed_out"):
            add("setup_error", "engine run timed out")
        elif experiment.get("returncode") not in (0, None):
            add("setup_error", f"engine exit {experiment['returncode']}")
        if experiment.get("software_renderer"):
            add("setup_error", f"software renderer {experiment.get('renderer')}")
    for line in gpu_failures(log_text or ""):
        add("gpu_compile", line)
    if grab is None:
        add("setup_error", "no grab retrieved")
    else:
        if grab["mean"] < args.brightness_low * 255:
            add("black", f"final grab mean luma {grab['mean']} < {args.brightness_low * 255:.2f}")
        elif grab["stddev"] < args.flatness * 255:
            add("flat", f"final grab luma stddev {grab['stddev']} < {args.flatness * 255:.2f}")
    p50 = final.get("p50_ms")
    if p50 is not None and p50 > args.budget_ms:
        add("over_budget", f"p50 {p50:.1f} ms > budget {args.budget_ms} ms")
    return findings


def summarize(findings):
    return "pass" if not findings else ",".join(sorted({f["kind"] for f in findings}))


def exit_status(results, fail_on_budget=False):
    hard = any(f["kind"] != "over_budget" for r in results for f in r["findings"])
    if hard or not results:
        return 1
    if any(r["findings"] for r in results):
        return 1 if fail_on_budget else 2
    return 0


def collect(folder):
    """Locate headless-test evidence under folder; returns (experiment, log, grab path)."""
    exps = sorted(Path(folder).glob("*/*/experiment.json"))
    if not exps:
        return None, "", None
    run = exps[0].parent
    experiment = json.loads(exps[0].read_text())
    log = (run / "engine.log").read_text(errors="replace") if (run / "engine.log").exists() else ""
    grabs = sorted((run / "grabs").glob("*.png"))
    return experiment, log, (grabs[-1] if grabs else None)


def archive_modes(archive):
    from tools import release

    with contextlib.redirect_stdout(io.StringIO()):  # verify() prints the manifest
        manifest = release.verify(archive, "armhf")
    names = set()
    for path in manifest.get("files", {}):
        m = re.fullmatch(r"modes/([^/]+)/main\.lua", path)
        if m:
            names.add(m.group(1))
    return sorted(names)


def ssh_options(host, known_hosts=None):
    """Same trust policy as eyesyctl: strict host keys, local/eyesy_known_hosts if present."""
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]+", host) or host.startswith("-"):
        raise SystemExit("Invalid hostname")
    options = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=yes"]
    if known_hosts is None and (ROOT / "local/eyesy_known_hosts").is_file():
        known_hosts = ROOT / "local/eyesy_known_hosts"
    if known_hosts:
        options += ["-o", f"UserKnownHostsFile={Path(known_hosts).resolve(strict=True)}"]
    return options


def verify_mode(execute, args, mode, out_dir):
    started = time.monotonic()
    run_error = None
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        execute(
            args.archive,
            args.host,
            args.clone_id,
            mode,
            args.frames,
            out_dir,
            ssh_options(args.host, args.known_hosts),
        )
    except Exception as exc:  # engine failure still leaves evidence; keep classifying
        run_error = f"{type(exc).__name__}: {exc}"
    experiment, log, grab_path = (None, "", None)
    if out_dir.exists():
        experiment, log, grab_path = collect(out_dir)
    grab = grab_stats(grab_path) if grab_path else None
    findings = classify(experiment, log, grab, args)
    if run_error and not any(f["kind"] == "setup_error" for f in findings):
        findings.insert(0, {"kind": "setup_error", "message": run_error})
    final = (experiment or {}).get("final") or {}
    return {
        "mode": mode,
        "status": summarize(findings),
        "passed": not findings,
        "findings": findings,
        "p50_ms": final.get("p50_ms"),
        "p95_ms": final.get("p95_ms"),
        "luma_mean": grab and grab["mean"],
        "luma_stddev": grab and grab["stddev"],
        "renderer": (experiment or {}).get("renderer"),
        "run_error": run_error,
        "wall_seconds": round(time.monotonic() - started, 1),
        "evidence": str(out_dir),
    }


def line(r):
    p50 = "-" if r["p50_ms"] is None else f"{r['p50_ms']:.1f}ms"
    luma = "-" if r["luma_mean"] is None else f"{r['luma_mean']:.1f}"
    text = f"{r['mode']:<32} {r['status'].upper() if r['passed'] else 'FAIL ' + r['status']:<28} p50={p50:<8} luma={luma:<6} {r['wall_seconds']}s"
    return text


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("archive", type=Path, help="armhf package archive")
    p.add_argument("--host", required=True)
    p.add_argument("--clone-id", required=True)
    p.add_argument("--mode", action="append", help="mode to test (repeatable; default all in archive)")
    p.add_argument("--known-hosts", type=Path, help="SSH known_hosts file (default local/eyesy_known_hosts)")
    p.add_argument("--frames", type=int, default=180)
    p.add_argument("--output", type=Path, required=True, help="new directory")
    p.add_argument("--budget-ms", type=float, default=33.3, help="p50 frame-time budget")
    p.add_argument("--fail-on-budget", action="store_true", help="treat over-budget as exit 1 not 2")
    p.add_argument("--brightness-low", type=float, default=0.0001, help="black below this mean luma (0-1)")
    p.add_argument("--flatness", type=float, default=0.002, help="flat below this luma stddev (0-1)")
    return p


def main(argv=None, execute=None):
    args = parser().parse_args(argv)
    if execute is None:
        from tools.headless_test import execute
    args.archive = args.archive.resolve()
    modes = archive_modes(args.archive)
    if args.mode:
        missing = [m for m in args.mode if m not in modes]
        if missing:
            raise SystemExit("Not in archive: " + ", ".join(missing))
        modes = list(dict.fromkeys(args.mode))
    if args.output.exists():
        raise SystemExit("Output directory already exists")
    args.output.mkdir(parents=True)
    results = []
    for mode in modes:
        result = verify_mode(execute, args, mode, args.output / "runs" / mode)
        (args.output / f"{mode}.json").write_text(json.dumps(result, indent=2) + "\n")
        results.append(result)
        print(line(result), flush=True)
        for f in result["findings"]:
            print(f"    {f['kind']}: {f['message']}")
    status = exit_status(results, args.fail_on_budget)
    summary = {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "archive": str(args.archive),
        "host": args.host,
        "frames": args.frames,
        "budget_ms": args.budget_ms,
        "exit_status": status,
        "counts": {
            "total": len(results),
            "passed": sum(r["passed"] for r in results),
        },
        "modes": results,
    }
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{summary['counts']['passed']}/{len(results)} passed, exit {status}")
    return status


if __name__ == "__main__":
    sys.exit(main())
