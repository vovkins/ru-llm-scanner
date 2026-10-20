# Distribution notices

The ru-llm-scanner code is Copyright (c) 2026 vovkins, licensed under MIT;
see LICENSE. This does not change the licenses of bundled dependencies or models.

## Detection code and rules

Analyzer and dictionary sources originate from
https://github.com/vovkins/ru-llm-proxy at
da4f50a87ddf8a6c160c5f1893f5bf526f713d1c. Its README declares MIT.
The owner selected MIT for ru-llm-scanner on 2026-10-20.
Exact source hashes and scanner adaptation patches are recorded in
upstream.lock.json; patches include capacity/offline integration and bounded NER
window recovery. These are scanner modifications, not an upstream release.

Gitleaks-derived rules retain the original MIT notice in THIRD_PARTY_NOTICES.md,
copied byte for byte from that upstream revision.

## NER model

Model: fef2/ner_rus_bert-secret_detection
https://huggingface.co/fef2/ner_rus_bert-secret_detection/tree/52b5b0745aac14f73fcf2ac0f91d9b5001a85ae4

Revision: 52b5b0745aac14f73fcf2ac0f91d9b5001a85ae4.
The pinned model manifest declares Apache-2.0; the full license text is included
in licenses/Apache-2.0.txt. The model files and weights are unmodified.
The pinned model artifact contains no separate NOTICE file. Provenance and all
six file hashes are retained in the source/runtime locks. The text of the license
is kept outside the model directory so its strict inventory remains unchanged.

## Python and native dependencies

Installed wheel license and notice files remain in the images' *.dist-info
directories. Debian copyright/license files remain in /usr/share/doc; shared
license texts are in /usr/share/common-licenses. Python/base image notices are
also retained. Do not remove these files when redistributing images.

The release includes inventories of installed distributions and native packages,
with versions and notice hashes. Each dependency retains its own license.
Debian package copyright files identify source projects and license terms;
https://sources.debian.org/ and https://snapshot.debian.org/ provide versioned
source archives. The release licensing guide explains the corresponding-source
material supplied alongside binary artifacts.
