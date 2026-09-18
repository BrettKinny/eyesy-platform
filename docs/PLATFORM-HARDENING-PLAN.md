# Platform Hardening Plan

Status: draft — ROADMAP item 7. Updated 2026-09-18.
Covers exactly two workstreams:
1. **Read-only root restoration qualification after apt changes.**
2. **Fully pinned package acquisition.**

This file only plans the work; it changes no other file. Every anchor below was
verified against the repository as of 2026-09-18.

---

## Goal

Close the two remaining platform supply-chain and boot-integrity gates so the
device's root filesystem can be trusted read-only and a release can be rebuilt
bit-for-bit on a clean machine:

1. A live provision of a development clone must install its apt prerequisites,
   mutate platform files, and restore the root mount to `ro,noatime`
   **in the same invocation**, exiting `0`, with no dependency on a reboot to
   clean up open descriptors. This qualifies ROADMAP item 7's read-only
   restoration claim and clears `docs/STATUS.md` gate 4.
2. Package acquisition — both the build container's apt surface and the
   device-provider's apt surface — must be pinned to a frozen point in time so a
   clean-machine rebuild reproduces the exact same package surface, and
   therefore the same byte-reproducible release. This clears `docs/STATUS.md`
   gate 5.

---

## Current state

### Workstream 1 — read-only root restoration (STATUS.md gate 4)

The provisioning script already implements a ro/rw/ro transaction:

- `tools/provision_device.sh:82` — `task_mount_options=$(findmnt -n -o OPTIONS /)`
  reads the live root mount options.
- `tools/provision_device.sh:84-90` — if the root is detected `ro`, it
  `mount -o remount,rw /` and sets `task_restore_ro=true`. Any failure here is
  fatal (`ERROR: failed to remount root filesystem read-write`) and exits `1`.
- `tools/provision_device.sh:102-113` — `cleanup()` is registered as an
  `EXIT` trap (`:114`). On exit it `sync`s (`:104`) and, if `task_restore_ro`,
  runs `mount -o remount,ro /` (`:105-108`). A failed restoration prints
  `ERROR: failed to restore the root filesystem read-only; reboot before using
  the clone`, forces the status nonzero, and explicitly `exit "$task_status"`
  so a failed remount can never be reported as success.
- `tools/provision_device.sh:115-121` — `apt-get update` and `apt-get install`
  of the Xorg/runtime prerequisites run between the rw remount and the trap.
- `tools/provision_device.sh:81` / `:149` — `dpkg-query -W` snapshots
  `packages.before` / `packages.after` into the idempotent
  `/sdcard/eyesy-platform/provision-backup/` (`:57-65` refuse any second
  backup).

**Why apt breaks the ro remount.** The only thing standing between the exit
trap and a `ro` root is `mount -o remount,ro /`, which returns `EBUSY` while any
process holds a writable file descriptor on the filesystem ("target is busy").
Apt's maintenance scripts (dpkg triggers such as `ldconfig`, `update-alternatives`,
`update-rc.d` for the installed units) and running daemons that write during the
transaction (systemd-journald log rotation, resolv/avahi/dhcpcd rewriting
`/etc/resolv.conf`, cron/anacron timers) commonly keep such a descriptor open at
the moment of remount. Closing all descriptors — i.e. a reboot — lets the same
remount succeed. This precisely matches the three recorded facts:

- `docs/DEPLOYMENT.md` (§ Build and stage): "The first spare-card provision
  completed, but immediate read-only remount failed after apt; a controlled
  reboot restored `ro,noatime`. Treat this cleanup limitation as unresolved,
  not a successful read-only restoration."
- `docs/STATUS.md:60-62`: "Apt initially prevented read-only remount; controlled
  reboot restored `ro,noatime`. Immediate post-apt cleanup remains a known
  provisioning limitation."
- `docs/STATUS.md:287-289` (gate 4): "Reliable immediate read-only restoration
  after provisioning apt changes. Failure now propagates as a nonzero exit;
  successful restoration still needs a future provisioning qualification, not
  another uncontrolled apt run tonight."

*Which specific process held the busy descriptor on the failed run was not
identified* — that attribution is [INFERENCE]; only the EBUSY-vs-reboot behavior
is measured.

**Where "qualified" currently stands.** The failure-detection side is
mechanically proven but unproven live: `evidence/reports/provision-hygiene-2026-09-15/`
shows 10 passing `tests/test_provision_device.py` cases, including
`test_cleanup_exit_status_reflects_remount_failure`,
`test_failed_read_write_remount_is_fatal`, and the preflight guard tests. Those
are mocked/local filesystem tests, not a live apt run — `docs/DEPLOYMENT.md`
explicitly notes "These newer checks are locally tested, not a second live apt
qualification."

### Workstream 2 — fully pinned package acquisition (STATUS.md gate 5)

What is already pinned and recorded:

- **Build base image by digest** — `tools/Containerfile:1`
  `ARG BASE_IMAGE=docker.io/library/debian@sha256:88200866…ea4171`, the slim
  multi-arch OCI index. `tools/Containerfile:3-4` asserts
  `EXPECTED_ARCH=amd64` against `dpkg --print-architecture` at build time; the
  arm variant pins the arm manifest of the same index (fixed by
  `bootstrap --arm`, see `docs/STATUS.md:181-185`).
- **SDK archive by digest** — `dependencies.lock.json` `openframeworks.armhf_sha256`
  and `sdk_lock.archive_sha256` = `e4b2a135…d90f2e0` (0.12.1).
- **Build provenance manifest** —
  `evidence/reports/bootstrap-arm-2026-09-15/provenance_json.txt` records the
  resolved image digest/ID, `sdk_lock`, `engine_sources` per-file SHA-256,
  `private_runtime_libraries` (libstdc++/libgcc), patches, and
  `build_packages_lock.contents` + its `sha256`.
- **A build-time package lock is already emitted** —
  `tools/Containerfile:13` and `:16` each run
  `dpkg-query -W > /build-packages.lock` after installing, and that surface is
  captured into the provenance manifest.

What still floats:

- **Apt repositories.** `tools/Containerfile:5-13` and `:15-16` run
  `apt-get update && apt-get install …` against Debian's **live** repositories
  (`deb.debian.org`), so a build on a later date resolves newer package versions
  than the recorded `build_packages_lock` — even though the base image layer is
  digest-pinned. The lockfile is therefore a *record* of what drifted, not a
  constraint on it. The device provider has the same problem:
  `tools/provision_device.sh:115-121` installs its prerequisite list from the
  device's floating Raspbian repository.
- **Lua runtime surface** — `dependencies.lock.json` `lua.source` =
  "Bookworm libluajit-5.1-dev" names a floating apt package, not a pinned
  revision.

---

## Gaps

- G1. No live proof that `provision_device.sh` restores `ro,noatime` in-process
  after a real apt run (STATUS.md gate 4 [unqualified]).
- G2. The busy-file-descriptor cause of the failed remount is unresolved; even if
  the trap succeeds today, a routine daemon write could regress it (mechanism
  unattributed, see the `[INFERENCE]` above).
- G3. Apt sources are floating for **both** the build container and the device
  provider; `build_packages_lock` records drift instead of preventing it.
- G4. No enforced artifact check that a rebuild's apt surface matches the
  recorded lock (the lock is emitted but never verified against a pinned ref).
- G5. No clean-machine reproducibility gate: a stale Docker cache or a different
  snapshot date could silently change package versions without failing the build.

---

## Plan

### Workstream 1 — qualify and harden read-only restoration

**Step 1.1 — Close G2: make the pre-apt environment remount-able.**
Before `mount -o remount,rw /` (`tools/provision_device.sh:84-90`), neutralize
known writable-descriptor holders for the duration of the transaction: stop the
apt-daily/anacron timer units and `systemd-resolved`/avahi/dhcpcd rewriting
`/etc/resolv.conf`, and run `ldconfig` triggers before restore. Optionally retry
`mount -o remount,ro /` a small number of times (e.g. 3 × 2 s) inside `cleanup()`
to ride out a transient journal rotate, while keeping the hard error + nonzero
exit for a true busy mount.

*Verification (unit-level, no device):* extend `tests/test_provision_device.py`
`ProvisionDeviceSafetyTests` with a case asserting the existing
`test_cleanup_exit_status_reflects_remount_failure` still forces nonzero and a
new case asserting a transient-busy remount that becomes available after a retry
is treated as success. Run the one module, not the whole suite:
`python3 -m unittest tests.test_provision_device -v`.

**Step 1.2 — LIVE qualification (closes G1; needs a device, owned by the
coordinator, not this task).** On the spare development clone with the root
already `ro,noatime`:

1. Confirm platform units inactive + disabled (the script refuses otherwise,
   `tools/provision_device.sh:26-35`).
2. Run `sudo bash tools/provision_device.sh CLONE_ID_FROM_RECEIPT`.
3. **Pass** requires, in the same invocation and without a reboot:
   - script exits `0`;
   - immediately after exit, `findmnt -n -o OPTIONS /` reports `ro,noatime`
     (no `rw`);
   - `/sdcard/eyesy-platform/provision-backup/packages.before` vs
     `packages.after` differ only by the script's documented prerequisite list
     (`tools/provision_device.sh:115-121`) plus their apt-resolved dependencies
     (audit the diff for anything unexpected), and no platform unit files
     changed other than the installed copies;
   - the clone marker `/etc/eyesy-development-clone` still matches `CLONE_ID`;
   - stock engine (`eyesypy.service`) is still active and platform services
     still disabled.
   **Fail** if the script exits nonzero, or the root is still `rw` at exit
   (requiring a reboot), matching the current known limitation.
4. Record the receipt under `evidence/reports/provision-qualified-YYYY-MM-DD/`
   and flip the read-only claim in the gates list.

*Deliverable:* a dated evidence report with the raw terminal transcript, the
`findmnt` line, and the two package inventories; the `hardware_validated: false`
flag in release manifests stays until physical bench acceptance (STATUS.md gates
1-2) regardless.

### Workstream 2 — fully pin package acquisition

**Step 2.1 — Pin build apt sources to a Debian snapshot.**
Add a `sources.list`/`sources.list.d` file to the build context that points
`apt-get update` at `snapshot.debian.org` with a fixed archive path, e.g.
`deb http://snapshot.debian.org/archive/debian/20260915T000000Z/ bookworm main`
(+ `bookworm-updates`/security equivalents), referenced from
`tools/Containerfile` so both `RUN apt-get` blocks (`:5-13`, `:15-16`) resolve a
frozen repo. The base image stays digest-pinned (`:1`); pinning the snapshot
freezes the layer *above* the base image that currently drifts.

*Verification:* `docker build` succeeds with `apt-get update` resolving only the
snapshot host (no `deb.debian.org` in the resolved sources), and the
`build_packages_lock` surface is stable across two builds a day apart on the
same snapshot date.

**Step 2.2 — Commit the apt lock as a checked-in reference.**
Persist the reference `build_packages_lock` (the frozen-surface `dpkg-query -W`
output) into `dependencies.lock.json` (or a sibling `apt-packages.lock` next to
it) with its `sha256`, alongside the existing `build_base` digest and
`sdk_lock`. This turns the file from a build-time byproduct into a reviewable,
reviewed artifact.

*Verification:* the committed lock parses, its `sha256` matches a current
snapshot build's emitted lock, and a reviewer diff against the known-good
reference is empty.

**Step 2.3 — Enforce the apt surface in the build.**
In the build step (or a tiny `tools/verify_apt_lock.py` invoked by the packager),
after installing, recompute `bash -c 'dpkg-query -W | sha256sum'` and fail the
build if it does not equal the committed reference `sha256`. The existing
provenance path already records `build_packages_lock.contents`/`sha256`
(`evidence/reports/bootstrap-arm-2026-09-15/provenance_json.txt`) — this step
makes a mismatch a hard error instead of a note.

*Verification:* a deliberate version bump in `sources.list`'s snapshot date makes
the build fail with the expected mismatch; restoring the pinned date makes it
pass.

**Step 2.4 — Pin the device provider apt surface.**
Point `tools/provision_device.sh`'s `apt-get update` (`:115`) at the same frozen
Raspbian snapshot the clone was imaged against and record the resolved
`packages.after` (already snapshotted at `:149`) as the device reference. This
pairs with Workstream 1's live qualification so the on-device surface is as
deterministic as the build surface.

*Verification:* two dry-run provisions against the frozen source resolve
identical candidate versions; `packages.after` hash is reproducible between
runs.

**Step 2.5 — Clean-machine reproducibility gate (closes G5).**
On a pristine worker: `docker builder prune -af` (fresh cache), clean git
checkout, then `./eyesyctl bootstrap --arm && ./eyesyctl build --arm &&
./eyesyctl package --arm` twice on the same pinned snapshot. Byte-reproducible
packaging then produces the same `dev-<payload-id>` release; the provenance
`build_packages_lock.sha256`, `sdk_lock.sha256`, and `image.digest` must be
identical across both runs.

*Verification for the whole gate:* the two runs produce (a) the same release
ID/manifest and (b) identical `build_packages_lock.sha256`. Any divergence is a
failed gate.

---

## Verification (summary)

- WS1 unit: `python3 -m unittest tests.test_provision_device -v` — existing
  remount-failure and new retry-recovery cases pass (Step 1.1).
- WS1 live: provision transcript + `findmnt -n -o OPTIONS /` = `ro,noatime` at
  exit, exit code 0, package inventory diff matches the documented list,
  stock engine untouched (Step 1.2).
- WS2 snapshot: `apt-get update` resolves only the pinned snapshot host; lock
  stable across two builds a day apart (Step 2.1).
- WS2 lock: committed `apt-packages.lock` sha matches a snapshot build's emitted
  lock (Step 2.2).
- WS2 enforcement: intentional snapshot-date bump fails the build with a lock
  mismatch; pinned date passes (Step 2.3).
- WS2 device: dry-run provisions resolve identical candidates; `packages.after`
  hash reproducible (Step 2.4).
- WS2 clean machine: two cache-wiped clean builds yield identical release ID and
  `build_packages_lock.sha256` (Step 2.5).

---

## Risks

- **Live attestation needs a device.** Workstream 1's gate-4 qualification
  happens on the spare clone, which the coordinator owns; this plan cannot
  execute it unattended. Until then, gate 4 stays "unqualified" (acceptable —
  the trap already makes failure loud and nonzero).
- **Snapshot availability.** `snapshot.debian.org` retention for bookworm and
  Raspbian (raspbian snapshot host) must cover the chosen date; an unpinned date
  reintroduces drift. Mitigation: pin a known-good, retained snapshot and record
  it in `dependencies.lock.json`.
- **Byte reproducibility is package-surface reproducibility, not bit identity.**
  Identical apt packages still embed image build timestamps and are rebuilt with
  different SOURCE_DATE_EPOCH-equivalents elsewhere. The plan gates the
  reproducible *surface* (same package set + same docker base digest + same SDK
  digest) and the byte-reproducible *release ID*; do not over-claim bit-level
  equality of embedded binaries if the existing packaging only guarantees
  release-ID equality.
- **`hardware_validated` interplay.** Flipping the read-only/pinned flags is a
  supply-chain signal only; the release manifest's `hardware_validated: false`
  remains until physical bench acceptance (STATUS.md gates 1-2), independent of
  this plan.
