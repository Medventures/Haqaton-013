# Task7 independent frozen-diff review

Reviewer p0_revisions (not frontend implementer). Spec compliance needs fixes; quality needs fixes.

Strengths: App103–112/149–153 revision/status-scoped gating and cancellation prevent stale cache resurrection; SourceEvidence17–22 conservatively detaches changed arrays. DocumentEditor18–33/129/146 iterates AI paths, preserving deleted/trailing/all-deleted original evidence. Source buttons outside disabled fieldset; server-time seek/abort/revoke sound.

Important1: TranscriptPanel24–30 resets dirty local draft whenever fetched revision changes, so reconnect/refetch can silently discard corrections. Preserve dirty snapshot until explicit reload or own successful save, with regression.

Important2: App144–157 late transcript PATCH completion clears shared selection/dirty flags without checking selected consultation. A→B navigation and editing B while A saves can lose B dirty guard. Scope completion to initiating consultation or block navigation; delayedsave/switch/edit regression.

Important3: TranscriptPanel96 textarea branches only on editing, not editable. Status becoming APPROVED/SENT_TO_MIS leaves existing editing textarea writable. App159 approval ignores transcriptDirty. Inputs must enforce readonly and unsaved transcript needs explicit resolution before approval.

Minor: PDF.js Node legacy advisory, Vite third-party comments/chunk warnings. Browser375px/keyboard actualacceptance Task9 pending. No suite rerun; read diff, targeted clinical.ts/defaults and cut-off DocumentEditor effect check. No mutations. All3 findings sent original implementer for TDD fixround1. Snapshot /tmp/medhub-p0-snapshots.BPZlzl/task-7-fix-base.
