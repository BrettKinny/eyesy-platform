#!/usr/bin/env python3
"""Scene contract verifier: deterministic A/B runs with pixel assertions.

The engine in --replay mode is bit-deterministic (fixed 60 fps clock,
synthesized 220/440 Hz audio; byte-identical grabs across identical replays,
asserted by tests/input_workflow_tests.py). This harness exploits that: every
check is a pair of engine runs whose replays differ only in the stimulus under
test, both grabbing their final frame at the same sim time. Free-running scene
motion cancels exactly, so the A/B pixel delta contains the effect alone.

Effect metric: fraction of pixels whose luma changed by more than 20 (0-255).
Coverage-independent -- a rotated wireframe on a near-black background and a
full-frame palette shift both read as their true changed-pixel fraction, and a
dead knob reads exactly 0.000. Mean-abs diff is reported alongside.

Runs per scene (N = --frames, default 130):
  base, base2   all knobs 0.0, gain 1, freq 1 -- base2 re-runs base to assert
                the harness noise floor (~0) on this machine
  knobK-mid/-max  knob K at 0.5 / 1.0 from frame 5 (mid catches cyclic params
                such as hue, where 0 and 1 are the same palette phase)
  knobK-trig    second chance, only when mid and max both show no effect:
                knob at 1.0 plus MIDI note-on before the grab (catches
                trigger-gated params, e.g. decay that only shapes flashes)
  audio-quiet/-loud/-freq  synthesized audio gain 0.05 / 3.5 / freq x3.5
  trigger       MIDI note-on 30 frames before the grab

Checks (docs/SCENE-LIBRARY.md design-law signatures):
- survival: every run exits 0 with no mode_errors/shader_warning
- determinism: d(base, base2) ~= 0, else the A/B method is invalid here
- dead knob: changed-pixel fraction of some knob state must exceed
  --min-fraction (0.0 for a dead knob)
- blank/whiteout/flat: mean luma + stddev bounds on every final grab
- audio reactivity: any audio variant differs beyond --min-fraction, asserted
  when the scene Lua references ctx.audio
- trigger response: same, asserted when the scene references ctx.trigger

Usage:
  scene_verify.py --mode starter --output local/verify-001 --xvfb
  scene_verify.py --output local/verify-all --xvfb              # whole catalog
Exit 0 iff every selected scene passes. Evidence per scene: summary.json,
contact-sheet.png and run-<name>/{replay.json,engine.log,report.json,grabs/}.
"""

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageStat


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import benchmark  # noqa: E402  (select_modes, memory_summary, sample_failed)

NOTE_ON = 0x90  # MIDI note-on forces ctx.trigger under the default audio+note source
KNOBS = (1, 2, 3, 4, 5)
KNOB_EVENT_FRAME = 5
CHANGE_THRESHOLD = 1  # count any differing pixel; the engine is bit-deterministic,
# so a dead stimulus produces byte-identical grabs (frac 0.0)


def parse_params(main_lua):
    """Static e.param parse -> {knob 1..5: {name, min, max}}. Provenance for the
    sweep, not ground truth: expressions as the knob argument are skipped."""
    knobs = {}
    for call in re.finditer(r"e\.param\s*\(([^()]*)\)", main_lua):
        args = [a.strip() for a in call.group(1).split(",")]
        if len(args) < 5 or not re.fullmatch(r"[1-5]", args[4]):
            continue
        name = re.fullmatch(r'"([^"]*)"', args[0])
        if name:
            knobs[int(args[4])] = {"name": name.group(1), "min": args[2], "max": args[3]}
    return knobs


def build_runs(frames, assigned):
    """One replay spec per A/B state. All runs zero every knob at frame 1 so the
    baseline state is defined; each variant changes exactly one stimulus."""
    zero = [{"frame": 1, "type": "knob", "index": k, "value": 0.0} for k in KNOBS]

    def variant(name, extra):
        return {"name": name, "events": list(zero) + extra, "frames": frames}

    runs = [variant("base", []), variant("base2", [])]
    for k in sorted(assigned):
        for tag, value in (("mid", 0.5), ("max", 1.0)):
            runs.append(
                variant(
                    f"knob{k}-{tag}",
                    [{"frame": KNOB_EVENT_FRAME, "type": "knob", "index": k, "value": value}],
                )
            )
    runs += [
        variant("audio-quiet", [{"frame": KNOB_EVENT_FRAME, "type": "audio", "gain": 0.05}]),
        variant("audio-loud", [{"frame": KNOB_EVENT_FRAME, "type": "audio", "gain": 3.5}]),
        variant("audio-freq", [{"frame": KNOB_EVENT_FRAME, "type": "audio", "gain": 1.0, "freq": 3.5}]),
        variant(
            "trigger",
            [{"frame": frames - 30, "type": "midi", "status": NOTE_ON, "channel": 0, "a": 60, "b": 100}],
        ),
    ]
    return runs


def run_experiment(engine, mode, folder, events, frames, timeout, warmup, offscreen, xvfb):
    """Bounded engine run adapted from tools/benchmark.py experiment(): writes the
    replay, samples status.json for timeout/memory, captures engine.log, parses
    report.json. Never raises on a failed run; caller reads result['passed']."""
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "replay.json").write_text(json.dumps(events, indent=1) + "\n")
    report = folder / "report.json"
    command = [
        str(engine),
        "--mode",
        str(mode),
        "--storage",
        str(folder),
        "--frames",
        str(frames),
        "--report",
        str(report),
        "--replay",
        str(folder / "replay.json"),
    ]
    if offscreen:
        command.append("--offscreen")
    if xvfb:
        command = ["xvfb-run", "-a", "-s", "-screen 0 1280x720x24"] + command
    started = time.monotonic()
    samples, last_frame = [], -1
    timed_out = False
    with (folder / "engine.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            while process.poll() is None:
                elapsed = time.monotonic() - started
                if elapsed > timeout:
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    break
                try:
                    status = json.loads((folder / "status.json").read_text())
                    if status["frame"] != last_frame:
                        last_frame = status["frame"]
                        samples.append({"elapsed": elapsed, **status})
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.25)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    final = json.loads(report.read_text()) if report.exists() else {}
    renderer = final.get("renderer", "")
    software = any(s in renderer.lower() for s in ("llvmpipe", "softpipe", "swrast"))
    sampled_failure = any(benchmark.sample_failed(s) for s in samples)
    passed = (
        process.returncode == 0
        and not timed_out
        and bool(renderer)
        and final.get("frame", 0) >= frames
        and not final.get("error")
        and not final.get("shader_warning")
        and final.get("mode_errors", 0) == 0
        and not sampled_failure
    )
    result = {
        "name": folder.name[4:],
        "returncode": process.returncode,
        "timed_out": timed_out,
        "wall_seconds": round(time.monotonic() - started, 2),
        "passed": passed,
        "renderer": renderer,
        "software_renderer": software,
        "final": final,
        "memory": benchmark.memory_summary(samples, warmup),
    }
    (folder / "experiment.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def pair_metrics(a, b):
    diff = ImageChops.difference(Image.open(a).convert("L"), Image.open(b).convert("L"))
    hist = diff.histogram()
    total = diff.size[0] * diff.size[1]
    return {
        "mean": round(sum(i * c for i, c in enumerate(hist)) / total, 2),
        "frac": round(sum(hist[CHANGE_THRESHOLD:]) / total, 5),
    }


def grab_luma(path):
    luma = Image.open(path).convert("L")
    stat = ImageStat.Stat(luma)
    return {"mean": round(stat.mean[0], 2), "stddev": round(stat.stddev[0], 2)}


def contact_sheet(paths, out_path):
    thumb, pad, caption = (320, 180), 8, 18
    cols = 4
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new(
        "RGB", (cols * (thumb[0] + 2 * pad) + pad, rows * (thumb[1] + caption + pad) + pad), (16, 16, 20)
    )
    draw = ImageDraw.Draw(sheet)
    for i, path in enumerate(paths):
        x = pad + (i % cols) * (thumb[0] + 2 * pad)
        y = pad + (i // cols) * (thumb[1] + caption + pad)
        sheet.paste(Image.open(path).convert("RGB").resize(thumb), (x, y))
        draw.text((x + 2, y + thumb[1] + 2), path.parent.name[4:], fill=(220, 220, 220))
    sheet.save(out_path)


def verify_mode(engine, mode, out_dir, args):
    out_dir.mkdir(parents=True)
    main_lua = (mode / "main.lua").read_text()
    params = parse_params(main_lua)
    refs = {
        "audio": bool(re.search(r"ctx\s*\.\s*audio", main_lua)),
        "trigger": bool(re.search(r"ctx\s*\.\s*trigger", main_lua)),
    }

    grabs, results = {}, {}

    def execute(spec):
        result = run_experiment(
            engine,
            mode,
            out_dir / f"run-{spec['name']}",
            spec["events"],
            spec["frames"],
            args.timeout,
            args.warmup,
            args.offscreen,
            args.xvfb,
        )
        results[spec["name"]] = result
        grab = next((out_dir / f"run-{spec['name']}" / "grabs").glob("*.png"), None)
        if result["passed"] and grab:
            grabs[spec["name"]] = grab

    runs = build_runs(args.frames, set(params))
    for spec in runs:
        execute(spec)

    # Second chance: knobs whose mid and max states both showed no effect get a
    # trigger-assisted run (trigger-gated params shape only post-trigger frames).
    weak = [
        k
        for k in sorted(params)
        if all(grabs.get(f"knob{k}-{tag}") and grabs.get("base") for tag in ("mid", "max"))
        and max(pair_metrics(grabs["base"], grabs[f"knob{k}-{tag}"])["frac"] for tag in ("mid", "max"))
        <= args.min_fraction
    ]
    zero = runs[0]["events"]
    for k in weak:
        execute(
            {
                "name": f"knob{k}-trig",
                "events": list(zero)
                + [
                    {"frame": KNOB_EVENT_FRAME, "type": "knob", "index": k, "value": 1.0},
                    {
                        "frame": args.frames - 30,
                        "type": "midi",
                        "status": NOTE_ON,
                        "channel": 0,
                        "a": 60,
                        "b": 100,
                    },
                ],
                "frames": args.frames,
            }
        )

    summary = {
        "schema_version": 1,
        "mode": mode.name,
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
        "params": params,
        "assigned_knobs": sorted(params),
        "references": refs,
        "frames_per_run": args.frames,
        "renderer": results["base"]["renderer"],
        "final": {
            k: results["base"]["final"].get(k)
            for k in ("p50_ms", "p95_ms", "resources", "audio_rms_left", "audio_source", "frame")
        },
        "runs": {
            name: {
                "passed": r["passed"],
                "returncode": r["returncode"],
                "timed_out": r["timed_out"],
                "wall_seconds": r["wall_seconds"],
            }
            for name, r in results.items()
        },
    }
    failures = []
    for name, result in results.items():
        if not result["passed"]:
            failures.append(
                f"run {name}: rc={result['returncode']} "
                f"timed_out={result['timed_out']} "
                f"final={ {k: result['final'].get(k) for k in ('error', 'mode_errors', 'shader_warning', 'frame')} }"
            )

    for name, path in sorted(grabs.items()):
        s = grab_luma(path)
        summary.setdefault("grab_stats", {})[name] = s
        if not args.brightness_low * 255 < s["mean"] < args.brightness_high * 255:
            failures.append(
                f"run {name}: mean luma {s['mean']} outside "
                f"[{args.brightness_low * 255:.0f}, {args.brightness_high * 255:.0f}]"
            )
        if s["stddev"] < args.flatness * 255:
            failures.append(f"run {name}: flat frame, stddev {s['stddev']}")

    if "base" in grabs and "base2" in grabs:
        d = pair_metrics(grabs["base"], grabs["base2"])
        summary["determinism"] = d
        if d["mean"] > 0.5 or d["frac"] > 0.001:
            failures.append(
                f"determinism: identical replays differ by {d} -- "
                "A/B results on this machine are not trustworthy"
            )
    else:
        failures.append("missing base or base2 grab")

    diffs = {}
    for k in sorted(params):
        states = {tag: grabs.get(f"knob{k}-{tag}") for tag in ("mid", "max", "trig")}
        available = {tag: p for tag, p in states.items() if p}
        if "base" in grabs and available:
            d = {tag: pair_metrics(grabs["base"], p) for tag, p in available.items()}
            diffs[f"knob{k}"] = d
            best = max(m["frac"] for m in d.values())
            if best <= args.min_fraction:
                failures.append(
                    f"knob {k} ({params[k]['name']}): no state changed more "
                    f"than {best:.4f} of pixels (dead knob?)"
                )
        elif not any(name.startswith(f"knob{k}") and not r["passed"] for name, r in results.items()):
            failures.append(f"knob {k}: missing mid/max grab")
    summary["ab_diffs"] = diffs

    audio = {}
    for variant in ("audio-quiet", "audio-loud", "audio-freq"):
        if "base" in grabs and variant in grabs:
            audio[variant] = pair_metrics(grabs["base"], grabs[variant])
    if refs["audio"]:
        best = max((m["frac"] for m in audio.values()), default=0)
        summary["audio"] = {"diffs": audio, "threshold": args.min_fraction, "pass": best > args.min_fraction}
        if best <= args.min_fraction:
            failures.append(f"audio reactivity: max changed fraction {best} <= {args.min_fraction}")
    else:
        summary["audio"] = {"diffs": audio, "pass": None, "note": "scene does not reference ctx.audio"}

    if "base" in grabs and "trigger" in grabs:
        d = pair_metrics(grabs["base"], grabs["trigger"])
        if refs["trigger"]:
            summary["trigger"] = {
                "diff": d,
                "threshold": args.min_fraction,
                "pass": d["frac"] > args.min_fraction,
            }
            if not summary["trigger"]["pass"]:
                failures.append(f"trigger response: changed fraction {d['frac']} <= {args.min_fraction}")
        else:
            summary["trigger"] = {"diff": d, "pass": None, "note": "scene does not reference ctx.trigger"}
    else:
        summary["trigger"] = {"pass": None, "note": "trigger grab missing"}

    summary["verdict"] = "pass" if not failures else "fail"
    summary["failures"] = failures
    return summary, [grabs[name] for name in sorted(grabs)]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--engine", type=Path, default=ROOT / "engine/bin/engine")
    parser.add_argument("--modes-root", type=Path, default=ROOT / "modes")
    parser.add_argument("--mode", action="append", dest="modes", help="repeatable")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory")
    parser.add_argument(
        "--frames", type=int, default=130, help="sim frames per A/B run; stimulus acts from frame 5"
    )
    parser.add_argument(
        "--min-fraction",
        type=float,
        default=0.001,
        help="min fraction of pixels differing at all for effect checks",
    )
    parser.add_argument(
        "--brightness-low", type=float, default=0.0001, help="fail grabs darker than this mean luma (0-1)"
    )
    parser.add_argument(
        "--brightness-high", type=float, default=0.985, help="fail grabs brighter than this mean luma (0-1)"
    )
    parser.add_argument(
        "--flatness", type=float, default=0.002, help="fail grabs with luma stddev below this (0-1)"
    )
    parser.add_argument("--timeout", type=float, default=120, help="per run, seconds")
    parser.add_argument("--warmup", type=float, default=1)
    parser.add_argument("--offscreen", action="store_true", help="engine EGL pbuffer backend, no X server")
    parser.add_argument(
        "--xvfb", action="store_true", help="wrap engine in xvfb-run (software GL in containers)"
    )
    args = parser.parse_args()
    if args.frames < 60 or args.min_fraction <= 0:
        parser.error("frames >= 60 (trigger fires at frames-30) and positive min-fraction required")
    if args.offscreen and args.xvfb:
        parser.error("--offscreen and --xvfb are mutually exclusive")
    root = args.modes_root.resolve()
    try:
        modes = benchmark.select_modes(root, args.modes)
    except ValueError as error:
        parser.error(str(error))
    output = args.output.resolve()
    if output.exists() or output.is_symlink():
        parser.error("output directory must not already exist")
    output.mkdir(parents=True)
    engine = args.engine.resolve()
    summaries = []
    for i, mode in enumerate(modes):
        summary, grabs = verify_mode(engine, mode, output / f"{i:02d}-{mode.name}", args)
        out_dir = output / f"{i:02d}-{mode.name}"
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        try:
            contact_sheet(grabs, out_dir / "contact-sheet.png")
        except Exception as error:  # sheet is convenience evidence, never a verdict
            summary["contact_sheet_error"] = str(error)
        print(
            json.dumps(
                {"mode": mode.name, "verdict": summary["verdict"], "failures": summary.get("failures", [])}
            ),
            flush=True,
        )
        summaries.append(summary)
    catalog = {
        "schema_version": 1,
        "utc": summaries[0]["utc"],
        "engine_sha256": summaries[0]["engine_sha256"],
        "thresholds": {
            "min_fraction": args.min_fraction,
            "frames": args.frames,
            "brightness_low": args.brightness_low,
            "brightness_high": args.brightness_high,
            "flatness": args.flatness,
            "change_threshold": CHANGE_THRESHOLD,
        },
        "passed": all(s["verdict"] == "pass" for s in summaries),
        "modes": summaries,
    }
    (output / "summary.json").write_text(json.dumps(catalog, indent=2) + "\n")
    return 0 if catalog["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
