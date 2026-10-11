#!/usr/bin/env python3
"""Replay frozen Lean sources in a fresh directory, retaining separate exits.

This evidence driver is outside the proved typed checker. It does not download
tools, select a global toolchain, or trust previously built local .olean files.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def toolchain_entries(root):
    result = []
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if name == "provenance" or name.startswith("provenance/") or name == "lean-4.19.0-linux.tar.zst":
            continue
        if path.is_symlink():
            result.append({"path": name, "symlink": os.readlink(path)})
        elif path.is_file():
            result.append({"path": name, "bytes": path.stat().st_size, "sha256": digest(path)})
    return result


def source_entries(root, expected):
    result = []
    for entry in expected:
        name = entry["path"]
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("invalid source manifest path")
        path = root / rel
        if path.is_symlink() or not path.is_file():
            raise ValueError("source is missing or is a symlink: " + name)
        result.append({"path": name, "bytes": path.stat().st_size, "sha256": digest(path)})
    return result


def command(cwd, evidence, name, argv, env):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    completed = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True)
    (evidence / (name + ".stdout")).write_text(completed.stdout)
    (evidence / (name + ".stderr")).write_text(completed.stderr)
    record = {"argv": argv, "cwd": str(cwd), "started_utc": started,
              "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "exit_status": completed.returncode,
              "stdout_sha256": digest(evidence / (name + ".stdout")),
              "stderr_sha256": digest(evidence / (name + ".stderr"))}
    (evidence / (name + ".json")).write_text(json.dumps(record, indent=2) + "\n")
    print(name + " exit " + str(completed.returncode), flush=True)
    if completed.returncode:
        raise RuntimeError(name + " failed; retained full output in " + str(evidence))
    return record, completed.stdout


def audit_dependencies(output, expected_names, allowlist):
    found = {}
    for line in output.splitlines():
        match = re.fullmatch(r"'([^']+)' depends on axioms: \[(.*)\]", line)
        if match:
            name, values = match.groups()
            axioms = sorted(x.strip() for x in values.split(",") if x.strip())
        else:
            match = re.fullmatch(r"'([^']+)' does not depend on any axioms", line)
            if not match:
                continue
            name, axioms = match.group(1), []
        if name in found:
            raise ValueError("duplicate theorem audit result: " + name)
        if set(axioms) - set(allowlist):
            raise ValueError("forbidden axiom dependencies: " + name + ": " + repr(axioms))
        found[name] = axioms
    if sorted(found) != sorted(expected_names):
        raise ValueError("axiom audit theorem list mismatch")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", required=True, type=Path)
    parser.add_argument("--workdir", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "frozen-sources.json").read_text())
    expected = manifest["sources"]
    if source_entries(root, expected) != expected:
        raise ValueError("proof source bytes differ from the frozen manifest")
    toolchain = args.toolchain.resolve()
    tool_manifest = json.loads((root / "evidence/toolchain-tree.json").read_text())
    tool_before = toolchain_entries(toolchain)
    if tool_before != tool_manifest["entries"]:
        raise ValueError("toolchain bytes differ from the recorded distribution tree")
    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=False)
    evidence = workdir / "replay-evidence"
    evidence.mkdir()
    for entry in expected:
        target = workdir / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / entry["path"], target)
    # These are child-process settings, not global environment/tool mutation.
    # Lean/Lake override variables and loader injection variables are omitted.
    env = {name: os.environ[name] for name in ("HOME", "LANG", "LC_ALL", "TZ") if name in os.environ}
    env["PATH"] = str(toolchain / "bin") + os.pathsep + "/usr/bin:/bin"
    commands = []
    rec, version = command(workdir, evidence, "01-lean-version", [str(toolchain / "bin/lean"), "--version"], env)
    commands.append(rec)
    if version.strip() != manifest["lean_version"]:
        raise ValueError("Lean version mismatch")
    rec, lake_version = command(workdir, evidence, "02-lake-version", [str(toolchain / "bin/lake"), "--version"], env)
    commands.append(rec)
    if lake_version.strip() != manifest["lake_version"]:
        raise ValueError("Lake version mismatch")
    rec, _ = command(workdir, evidence, "03-clean-build", [str(toolchain / "bin/lake"), "build", "HermesTicket"], env)
    commands.append(rec)
    rec, audit = command(workdir, evidence, "04-kernel-audit",
                         [str(toolchain / "bin/lake"), "env", str(toolchain / "bin/lean"), "HermesTicket/KernelAudit.lean"], env)
    commands.append(rec)
    dependencies = audit_dependencies(audit, manifest["audited_theorems"], manifest["allowed_axioms"])
    if source_entries(workdir, expected) != expected or source_entries(root, expected) != expected:
        raise ValueError("source bytes changed during replay")
    if toolchain_entries(toolchain) != tool_before:
        raise ValueError("toolchain bytes changed during replay")
    record = {"status": "pass", "proof_scope": "typed_checker_model_only",
              "sources_sha256": digest(root / "frozen-sources.json"),
              "toolchain_tree_sha256": digest(root / "evidence/toolchain-tree.json"),
              "allowed_axioms": manifest["allowed_axioms"], "actual_dependencies": dependencies,
              "source_bytes_unchanged": True, "toolchain_bytes_unchanged": True,
              "local_build_artifacts_reused": False, "commands": commands}
    (evidence / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print("clean replay PASS; typed checker model only", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        sys.exit(1)
