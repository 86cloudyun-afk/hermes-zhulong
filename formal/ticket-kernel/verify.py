#!/usr/bin/env python3
"""Verify reviewed identities and replay the typed proof with local pinned tools."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import subprocess
import sys
import tarfile


SOURCE_MANIFEST_SHA = "cd3fa704215fa48dec4215fa0ffd57b6ff4bf5994becddf06a21bdefd0b15f69"
TOOL_MANIFEST_SHA = "7c890479b405c695b835d0d7d81affad13c082975bde6ead33e608a57d9f12e2"
CHECKER_SHA = "232a90b524f8c248d764950bc021ab9fe2cc731c379fe5519b58bc99862fbbd2"
ARCHIVE_SHA = "6fe3ce97a58f44e2b3567d455b994eacec5bfe9ae7774f2a573444480ba813fe"
ARCHIVE_BYTES = 343842845
SOURCE_COMMIT = "6caaee842e9495688c1567e78c0e68dbb96942aa"
ARCHIVE_NAME = "lean-4.19.0-linux.tar.zst"
ARCHIVE_PREFIX = "lean-4.19.0-linux"
ARCHIVE_URL = "https://github.com/leanprover/lean4/releases/download/v4.19.0/" + ARCHIVE_NAME
ALLOWED_AXIOMS = {"propext", "Quot.sound", "Classical.choice"}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check_package(root):
    for name, expected, label in [
        ("frozen-sources.json", SOURCE_MANIFEST_SHA, "frozen source manifest"),
        ("evidence/toolchain-tree.json", TOOL_MANIFEST_SHA, "toolchain manifest")]:
        path = root / name
        if path.is_symlink() or digest(path) != expected:
            raise ValueError(label + " identity mismatch")
    manifest = json.loads((root / "frozen-sources.json").read_text())
    tools = json.loads((root / "evidence/toolchain-tree.json").read_text())
    public_theorems = []
    for entry in manifest["sources"]:
        rel = Path(entry["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("unsafe source manifest path")
        path = root / rel
        if path.is_symlink() or path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
            raise ValueError("frozen source bytes mismatch: " + entry["path"])
        if path.suffix == ".lean":
            public_theorems.extend("HermesTicket." + name for name in
                                   re.findall(r"^[ \t]*theorem\s+(\w+)", path.read_text(), re.M))
    if len(manifest["sources"]) != 14 or len(public_theorems) != 83:
        raise ValueError("reviewed source/theorem count mismatch")
    if sorted(public_theorems) != sorted(manifest["audited_theorems"]):
        raise ValueError("public theorem audit coverage mismatch")
    if set(manifest["allowed_axioms"]) != ALLOWED_AXIOMS:
        raise ValueError("axiom policy mismatch")
    if tools["source_commit"] != SOURCE_COMMIT or tools["archive_sha256"] != ARCHIVE_SHA:
        raise ValueError("toolchain provenance mismatch")
    return tools["entries"]


def check_checker(root):
    checker = root.parents[1] / "certified_ticket.py"
    if checker.is_symlink() or digest(checker) != CHECKER_SHA:
        raise ValueError("Python checker identity mismatch")
    return CHECKER_SHA


def runtime_entries(toolchain, allow_setup_records=False):
    entries = []
    for path in sorted(toolchain.rglob("*")):
        name = path.relative_to(toolchain).as_posix()
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
            raise ValueError("special toolchain file: " + name)
        if allow_setup_records and (name == "provenance" or name.startswith("provenance/")):
            if stat.S_ISLNK(mode):
                raise ValueError("symlink in excluded setup records")
            continue
        if allow_setup_records and name == ARCHIVE_NAME:
            if not stat.S_ISREG(mode) or path.stat().st_size != ARCHIVE_BYTES or digest(path) != ARCHIVE_SHA:
                raise ValueError("retained toolchain archive identity mismatch")
            continue
        if stat.S_ISLNK(mode):
            entries.append({"path": name, "symlink": os.readlink(path)})
        elif stat.S_ISREG(mode):
            entries.append({"path": name, "bytes": path.stat().st_size, "sha256": digest(path)})
    return entries


def check_toolchain(toolchain, expected, allow_setup_records=False):
    actual = runtime_entries(toolchain, allow_setup_records)
    if [x["path"] for x in actual] != [x["path"] for x in expected]:
        raise ValueError("toolchain file set mismatch")
    if actual != expected:
        raise ValueError("toolchain bytes mismatch")


def run_record(evidence, name, argv):
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = subprocess.run(argv, capture_output=True, text=True)
    (evidence / (name + ".stdout")).write_text(result.stdout)
    (evidence / (name + ".stderr")).write_text(result.stderr)
    record = {"argv": argv, "started_utc": started,
              "finished_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "exit_status": result.returncode,
              "stdout_sha256": digest(evidence / (name + ".stdout")),
              "stderr_sha256": digest(evidence / (name + ".stderr"))}
    (evidence / (name + ".json")).write_text(json.dumps(record, indent=2) + "\n")
    if result.returncode:
        raise RuntimeError(name + " exited " + str(result.returncode))
    return result.stdout


def validate_archive(archive, evidence):
    if archive.stat().st_size != ARCHIVE_BYTES or digest(archive) != ARCHIVE_SHA:
        raise ValueError("official archive size/SHA identity mismatch")
    proc = subprocess.Popen(["zstd", "-dc", str(archive)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    members = []
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != ARCHIVE_PREFIX or ".." in parts or member.name.startswith("/"):
                    raise ValueError("unsafe archive member path")
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError("unsupported archive member type")
                if member.issym() or member.islnk():
                    target = (posixpath.join(posixpath.dirname(member.name), member.linkname)
                              if member.issym() else member.linkname)
                    resolved = PurePosixPath(posixpath.normpath(target))
                    if resolved.is_absolute() or not resolved.parts or resolved.parts[0] != ARCHIVE_PREFIX:
                        raise ValueError("archive link escapes the toolchain")
                members.append({"name": member.name, "type": member.type.decode("ascii"),
                                "linkname": member.linkname})
        proc.stdout.read()
        stderr = proc.stderr.read().decode()
        exit_status = proc.wait()
    except Exception:
        proc.kill()
        proc.wait()
        raise
    finally:
        proc.stdout.close()
        proc.stderr.close()
    record = {"argv": ["zstd", "-dc", str(archive)], "exit_status": exit_status,
              "stderr": stderr, "members": members}
    (evidence / "archive-validation.json").write_text(json.dumps(record, indent=2) + "\n")
    if exit_status:
        raise ValueError("archive decompression failed")


def prepare_toolchain(cache, expected, evidence):
    cache.mkdir(parents=True, exist_ok=True)
    toolchain = cache / ARCHIVE_PREFIX
    if toolchain.exists():
        check_toolchain(toolchain, expected)
        return toolchain
    archive = cache / ARCHIVE_NAME
    if not archive.exists():
        partial = cache / (ARCHIVE_NAME + ".partial")
        if partial.exists() or partial.is_symlink():
            raise ValueError("partial download already exists; preserved")
        metadata = run_record(evidence, "download", [
            "curl", "--disable", "--fail", "--show-error", "--silent", "--location",
            "--proto", "=https", "--proto-redir", "=https", "--tlsv1.2",
            "--connect-timeout", "30", "--max-time", "600", "--output", str(partial),
            "--write-out", "%{http_code}\n%{ssl_verify_result}\n%{size_download}\n%{num_redirects}\n",
            ARCHIVE_URL])
        values = metadata.splitlines()
        if len(values) != 4 or values[:2] != ["200", "0"] or int(values[2]) != ARCHIVE_BYTES:
            raise ValueError("official download HTTP/TLS/size mismatch")
        if partial.stat().st_size != ARCHIVE_BYTES or digest(partial) != ARCHIVE_SHA:
            raise ValueError("downloaded archive size/SHA identity mismatch")
        partial.rename(archive)
    validate_archive(archive, evidence)
    toolchain.mkdir(exist_ok=False)
    run_record(evidence, "extract", ["tar", "--zstd", "-xf", str(archive),
                                    "--strip-components=1", "--no-same-owner",
                                    "--directory", str(toolchain)])
    check_toolchain(toolchain, expected)
    return toolchain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, help="existing official pinned toolchain; no download")
    parser.add_argument("--cache-dir", type=Path, help="task-local official download/extraction cache")
    parser.add_argument("--workdir", type=Path, help="new replay directory; never deleted or reused")
    parser.add_argument("--evidence-dir", type=Path, help="new verification log directory")
    args = parser.parse_args()
    if args.toolchain and args.cache_dir:
        parser.error("choose --toolchain or --cache-dir")
    root = Path(__file__).resolve().parent
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + str(os.getpid())
    workdir = (args.workdir or root / ".replays" / run_id).resolve()
    evidence = (args.evidence_dir or root / ".verification" / run_id).resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    result = {"status": "failed", "proof_scope": "typed_checker_model_only",
              "source_manifest_sha256": SOURCE_MANIFEST_SHA, "toolchain_manifest_sha256": TOOL_MANIFEST_SHA,
              "archive_sha256": ARCHIVE_SHA, "archive_bytes": ARCHIVE_BYTES,
              "source_commit": SOURCE_COMMIT, "publisher_digest": None,
              "independent_publisher_checksum_verified": False,
              "distribution_trust": "official_release_verified_TLS_and_local_artifact_pin"}
    try:
        if workdir.exists():
            raise ValueError("replay directory already exists")
        expected = check_package(root)
        result["checker_sha256_before"] = check_checker(root)
        external = args.toolchain is not None
        toolchain = (args.toolchain.resolve() if external else
                     prepare_toolchain((args.cache_dir or root / ".toolchain").resolve(), expected, evidence))
        check_toolchain(toolchain, expected, allow_setup_records=external)
        result["toolchain"] = str(toolchain)
        result["external_nonruntime_setup_records_excluded"] = external and (toolchain / "provenance").exists()
        run_record(evidence, "replay", [sys.executable, "-I", str(root / "replay.py"),
                                       "--toolchain", str(toolchain), "--workdir", str(workdir)])
        result["replay_exit_status"] = 0
        replay = json.loads((workdir / "replay-evidence/result.json").read_text())
        dependencies = replay["actual_dependencies"]
        if replay["status"] != "pass" or len(dependencies) != 83:
            raise ValueError("clean replay status/theorem count mismatch")
        if set(dependencies["HermesTicket.rowCertificateSound"]) != ALLOWED_AXIOMS:
            raise ValueError("general theorem foundation closure mismatch")
        for name in ["sampleAccepted", "alternateAccepted", "sampleUnsortedAccepted", "alternateProgramDifferent"]:
            if dependencies["HermesTicket." + name]:
                raise ValueError("positive fixture foundation closure mismatch")
        if [record["exit_status"] for record in replay["commands"]] != [0, 0, 0, 0]:
            raise ValueError("separate proof command exit mismatch")
        if not replay["source_bytes_unchanged"] or not replay["toolchain_bytes_unchanged"]:
            raise ValueError("replay byte stability mismatch")
        check_package(root)
        result["checker_sha256_after"] = check_checker(root)
        check_toolchain(toolchain, expected, allow_setup_records=external)
        result.update(status="pass", audited_theorems=83,
                      replay_result_sha256=digest(workdir / "replay-evidence/result.json"),
                      allowed_axioms=sorted(ALLOWED_AXIOMS), local_proof_objects_reused=False)
        print("PASS: frozen typed proof, 83 theorem closures, unchanged Python checker")
        print("Verification logs: " + str(evidence))
        print("Clean proof logs: " + str(workdir / "replay-evidence"))
    except Exception as exc:
        result["reason"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        sys.exit(1)
