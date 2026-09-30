# Independent backup-only review

Reviewer: /root/p0_preview (did not implement backup). Spec compliance: needs fixes. Code quality: needs fixes.

Strengths: pinned read snapshot, exclusive mode0600 reservation, integrity/table-count verification, fixed safe errors, synthetic WAL/concurrent-snapshot/failure coverage.

Important blocker: script closes reserved fd then sqlite3.connect reopens mutable destination pathname. Disposable /tmp symlink-swap probe overwrote an existing writable target DB and returned verified true. Failure cleanup checks inode then unlinks name, creating a second replacement race. Stage/verify privately and publish atomically without overwrite, or enforce a private trusted destination directory; verify published identity/mode. Original implementer assigned regression and fix before use.

No suite rerun by reviewer. Original report: focused8; full173 passed/23 optional PG skips/1 pre-existing warning. Review covers only backup, not acceptance/rollout. No real data was used or affected.
