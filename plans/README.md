# Plans

Execution order: 001 → 002 → 003. Each builds on the previous commit.

| # | Plan | Status | Depends on |
|---|---|---|---|
| 001 | [Camera server hardening + test baseline](001-camera-server-hardening.md) | DONE: approved, commit 3e0f1a1 on branch `worktree-agent-aa393ef611252490d`, not merged | — |
| 002 | [Paper region calibration (M-1)](002-paper-region-calibration.md) | DONE: approved, commit d5f576d on branch `worktree-agent-aaddf3d3f2df9cee2` (includes 001), not merged | 001 |
| 003 | [Calibration robustness](003-calibration-robustness.md) | DRAFT | 002 |

## Decisions from the design-doc grilling (2026-10-29)

- **Translation:** v1 plays the paper layout and swaps the output instrument (option a). Remapping to other layouts (b) and re-voicing real instruments (c) are future work.
- **Camera:** the phone sits on a stand looking straight down; a slight tilt is tolerated. Angled views are future work.
- **Transport:** iPhone over ngrok to localhost:5000 for now. Free upgrades later: Cloudflare quick tunnel, or LAN HTTPS with mkcert.
- **Template:** black ink on white US Letter, landscape. Regions are solid black boxes or black-outlined white areas, and solid wins where they overlap. Regions are numbered 1..N left to right, which gives chromatic order on a piano drawing. Note names (C4, C#4, ...) come later, anchored to MIDI numbers.
- **Repo:** this repo is the master repo. Tap Strap code joins it when strap work starts.
- **Parked:** synth choice (default idea: built-in Windows GS synth via mido), instrument switching UX, strap M0 measurements, lift detection for note length (test, then decide; fixed length is the fallback), light-coloured desks.
- **Reminder owed to the user:** when 002 lands, take 3 S-key snapshots (normal light, dim light, slight tilt) for fixtures.

Considered and rejected: binding to 127.0.0.1 (transport may move to LAN HTTPS, which needs LAN reachability); the ngrok URL in git history (it's a hostname, not a credential).
