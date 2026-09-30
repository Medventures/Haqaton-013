# New user additions while P0 workers run

2026-09-30. These additions do not cancel approved P0; new product scope is in brainstorming, NOT implementation-approved yet.

## User requests

1. Branded PDF with our logo/name and QR similar in presentation to Kazakhstan healthcare documents.
2. Empty/unmentioned clinical fields behind Add controls; omit empty clinical values from printed output.
3. diseases.json name/URL catalog points to protocols containing data needed for checks.
4. Parallel worker uses Canva plugin to create presentation with actual system screenshots.

## Confirmed choices and findings

- User chose PUBLIC verification of document authenticity WITHOUT medical data, not authenticated document opening.
- User chose ONLY Kazakhstan protocols; physician chooses the version.
- Proposed brand assumption: existing MedHub and stethoscope icon (public/favicon.svg / App Mark). No separate logo file found in scoped source search.
- Actual dataset is diseases.json (not disease.json): 3206 objects, exactly name/url; 3206 uniqueURLs, 168 duplicated disease names. It mixes countries and reference articles; no structured checklist fields. User file untouched.
- Read two public sample links: MedElement J20.9 page12274 is reference article, HELLP page17522 is RK2022 protocol. Do not assume all catalog entries are current RK official protocols.
- Root explained QR means MedHub issuance/integrity verification, NOT government confirmation or EDS. Proposed only issuance/status/date/hash, no names/diagnoses/public document download. Proposed local hash comparison to frozen PDF bytes; exact architecture needs written spec/plan approval.
- Read-only worker audit: approved_file in main.py regenerates PDF/DOCX every GET; approval freezes JSON only. No artifact/hash/public ID/PUBLIC_BASE_URL yet. New immutable artifact record/store + opaque publicID + final-byteSHA256 needed; lazy issuance for legacy approved JSON. Previously downloaded bytes cannot be retroactively verified. PDF projection emits EMPTY, DOCX separate paragraph projection requires coordinated sparse filtering while preserving explicit negatives and source templates.
- Earlier45–75min ETA applied ONLY oldP0; user was explicitly told additions expand scope.

## Pending clarification/design gates

- Async question pending: approve RKprotocol selection -> AI-drafted checklist with sourcecitations -> physician verifies list -> missing values entered manually, no autofill normal/diagnosis; protocolanalysis uses configuredOpenAI. Alternatives manuallycuratedlists or linksonly.
- After concept approval: architecturalwritten spec -> userreview -> writing-plan -> userexecution choice (parallel desired already, still artifactreviewgate). PublicQR upgraded first feature from bounded toarchitecture. Do NOT implement unapproved newrequirements inside existingTasks.
- PUBLIC_BASE_URL/public domain still unknown; need safe configured origin (never Host-derived URL/token/PHI). Discuss localhost limitation without claiming publicavailability.

## Canva assignment

- Root fully read plugin-management skill; available Canva tools discovered. Verified connection via canva_search_designs queryMedHub limit1 (successful). Returned unrelated CV design; NEVER modifyit. No plugin install needed.
- p0_revisions seat interrupted read-onlyverificationaudit and assigned Canva preparation. It must read skill, coordinate with p0_preview for isolatedsynthetic screenshotassets, never inspect/upload realconsultations/.env/userDB. No Canva writes/uploads until presentation purpose/shortdesignapproved. No application/README/harness edits.
- Async purposequestion pending: physicians/clinicmanagement, hackathonjury, investors/partners.
- Purpose resolved by user: jury of MedHub Haqaton (https://haqaton.medhubhaq.ai/), track AI-assistant for consultation sheet. User pasted problem/MVP/privacy/stack/Docker+Compose UMC requirements. Root inspected public HTML+JS after webtool failed; public UI requires PDF submission; official template/account unavailable. No account access attempted.
- USER APPROVED shortdesign and roles:12Russian16:9slides problem;solution/MVP;recording/transcript;fieldfilling;physicianreview;sources/revisions;privacy;architecture/Docker;API/MockMIS;testresults;roadmap;team. Team «ВАКСИНА АЙ»: Абай Кандышев business; Нурсултан Нургалиев technical; Измуханов Данияр technical; Артем Погорелов medic.
- Approval sent p0_revisions: may create ONE new Canva presentation/upload verified synthetic screenshots. Follow actual toolrequirements incl preview-before-editcommit ifneeded; no sharingpolicychange. Need editablelink; PDFexportnotexposed in listed tools, investigate honestly/manualexportfallback. MockMISonly, heuristicPIIlimits, no fabricated savings/testcounts/Dockerruntimeclaims. Presentation worker currently running.
- Initial12pageCanvadeck created: designDAHWqaMc-Ds, https://canva.link/7gne4dy56nun973 . PRELIMINARY, notfinal: screenshots/contentcorrectionpending. Worker noticedgenerateddeck omittedteamroles/stack/testevidence and willcorrectviaeditingtransaction; previewapprovalbeforecommitmayberequired. p0_revisions performedTask7independentreview duringgenerationwait, nowreturnsCanvapresentation.
- Intended deliverable editableCanva presentationwith actualsystem screenshots, no fabricatedUI; optionallocalexportifavailable. Roadmap-only for newQR/protocol/sparse features until actuallyimplemented. No sharingpolicy/publicpublish/email changes.
- Canva tools available: create_design; create_upload_url supports one-use rawbytesPOST (notbase64/multipart). Inspect toolmetadata carefully: brandedkit request differs from ordinarycreate, legacytools restrictions conflictmustresolveby taskactualbrandingneed. Root has not called generation/uploads.
- p0_preview owns synthetic acceptanceharness, was told coordinate safe screenshotswith presentationworker. p0_panels still owns frontendTask7 then independentTask5review. Task5 reviewpackage task-5-review.md ready (50kchars), Task5frozenreport219pass/2concurrentmissingharnessfailures.
