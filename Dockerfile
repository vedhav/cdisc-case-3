# =============================================================================
# CDISC Case 3 agent image  (full USDM -> TLF pipeline)
#
# Extends mediforce-golden-image (R + tidyverse + Python + Claude Code) with the
# R stack the six pipeline skills need at run time:
#   - ADaM derivation:   admiral, admiraldev, metacore, metatools
#   - ARD (numbers):      cards, cardx  (+ emmeans, mmrm, survival, broom.helpers)
#   - display:            gtsummary, gt, tfrmt, rtables, rlistings, ggsurvfit, ggplot2
#   - data plumbing:      dplyr, tidyr, haven, jsonlite
#   - Python:             pyyaml (skills + step scripts)
# plus the deterministic step script (open_skill_pr.py). No study data is bundled —
# the USDM + SDTM datasets are uploaded together at the Upload inputs step each run.
#
# NOTE: `siera` is deliberately NOT installed. The ARS-native CRAN package's back
# end is not production-grade; the tlf-generator skill drafts analysis R directly
# on cards/cardx + emmeans instead (see its generation-idioms reference).
#
# Skills are NOT baked in — they are read at run time from the repo via the
# workflow's externalSkillsRepo + skillsDir. Only the R/Python packages, the
# step scripts, and the fixtures need to be in the image.
#
# Build by hand (needs mediforce-golden-image):
#   docker build -t mediforce-agent:cdisc-case-3 .
#
# Build commands are kept QUIET on purpose: the platform builds with
# execSync(stdio:'pipe') and Node's 1MB maxBuffer; a chatty build overflows it
# and the build is killed.
# =============================================================================

FROM mediforce-golden-image

# --- ADaM derivation stack ---
RUN install2.r --error --skipinstalled \
      admiral admiraldev metacore metatools > /dev/null 2>&1

# --- ARD (numbers) + models ---
RUN install2.r --error --skipinstalled \
      cards cardx emmeans mmrm survival broom broom.helpers > /dev/null 2>&1

# --- Display / rendering ---
RUN install2.r --error --skipinstalled \
      gtsummary gt tfrmt rtables rlistings ggsurvfit ggplot2 > /dev/null 2>&1

# --- Data plumbing ---
RUN install2.r --error --skipinstalled \
      dplyr tidyr haven jsonlite > /dev/null 2>&1

# --- Python deps for the step scripts / skills ---
#   pyyaml            skills + step scripts
#   jsonschema        validate_ars.py — ARS LDM schema gate
#   cdisc-rules-engine  validate_core.py — CDISC Open Rules Engine (CLI `core`)
RUN pip install --no-cache-dir --break-system-packages \
      pyyaml jsonschema cdisc-rules-engine > /dev/null 2>&1

# --- Deterministic step scripts + baked-in schemas ---
#   container/ carries build_traceability.py, open_skill_pr.py, validate_ars.py,
#   generate_define.py, validate_core.py, and schemas/ars_ldm.schema.json.
COPY container/ /app/container/

# --- CDISC CORE rules cache (optional at build time) ---
# The rules engine needs a rules cache. Populate it here if a CDISC Library API
# key is supplied as a build arg (docker build --build-arg CDISC_LIBRARY_API_KEY=…);
# non-fatal so the image still builds without it (the gate then reports
# status=core-unavailable and proceeds unless CORE_REQUIRED=true).
ARG CDISC_LIBRARY_API_KEY=""
ENV CDISC_LIBRARY_API_KEY=${CDISC_LIBRARY_API_KEY}
RUN if [ -n "$CDISC_LIBRARY_API_KEY" ]; then \
      core update-cache > /dev/null 2>&1 || echo "core update-cache failed — cache not populated"; \
    fi

WORKDIR /workspace
