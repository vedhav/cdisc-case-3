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
# plus the deterministic step scripts (stage_inputs.py, open_skill_pr.py). No study
# data is bundled — the USDM + SDTM (+ optional CSR ground truth) are uploaded at
# the Provide inputs step each run.
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
      admiral admiraldev metacore metatools > /dev/null

# --- ARD (numbers) + models ---
RUN install2.r --error --skipinstalled \
      cards cardx emmeans mmrm survival broom broom.helpers > /dev/null

# --- Display / rendering ---
RUN install2.r --error --skipinstalled \
      gtsummary gt tfrmt rtables rlistings ggsurvfit ggplot2 > /dev/null

# --- Data plumbing ---
RUN install2.r --error --skipinstalled \
      dplyr tidyr haven jsonlite > /dev/null

# --- Python deps for the step scripts / skills ---
RUN pip install --no-cache-dir --break-system-packages pyyaml > /dev/null

# --- Deterministic step scripts (stage_inputs.py, open_skill_pr.py) ---
COPY container/ /app/container/

WORKDIR /workspace
