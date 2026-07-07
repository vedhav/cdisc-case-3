# =============================================================================
# CDISC Case 3 agent image
#
# Extends mediforce-golden-image (R + tidyverse + Python + Claude Code) with:
#   - the ARD + render stack (cards, cardx, gtsummary, gt, ggplot2) and the
#     model/survival helpers the custom efficacy path drafts against
#     (broom, survival, emmeans)
#   - the deterministic step scripts (stage_inputs.py, bind_validate.py,
#     classify_outputs.py, run_standard.R, package.R), the recipe library
#     (container/recipes/) for the standard safety outputs, and draft_custom.R
#     (the reference the custom-output agent step adapts)
#   - the bundled CDISCPILOT01 reference (ARS Reporting Event + ADaM) and the
#     pinned ARS v1.0 JSON schema, under /app/fixtures
#
# NOTE: `siera` is deliberately NOT installed. The ARS-native CRAN package is
# pre-1.0 and its back end is not production-grade; the agent drafts analysis R
# directly on cards/cardx instead (see the draft-custom-programs skill). See PLAN-3 §3.
#
# Skills are NOT baked in — they are read at run time from the repo via the
# workflow's externalSkillsRepo + skillsDir. Only the R packages, the scripts,
# the recipes, and the fixtures need to be in the image.
#
# Build by hand (needs mediforce-golden-image):
#   docker build -t mediforce-agent:cdisc-case-3 .
#
# Build commands are kept QUIET on purpose: the platform builds with
# execSync(stdio:'pipe') and Node's 1MB maxBuffer; a chatty build overflows it
# and the build is killed.
# =============================================================================

FROM mediforce-golden-image

# --- ARD + render stack. cards/cardx/gtsummary produce and display the ARD;
#     ggplot2 renders figures; broom/survival/emmeans back the custom efficacy
#     programs the agent drafts (ANCOVA LS means, Kaplan-Meier, Cox HR). ---
RUN install2.r --error --skipinstalled \
      cards cardx gtsummary gt ggplot2 broom survival emmeans jsonlite > /dev/null

# --- Deterministic step scripts + the standard-output recipe library ---
COPY container/ /app/container/

# --- Interactive traceability visualization (template + shared graph builder).
#     package.R -> build_trace.py injects the run's graph into the template to
#     emit /output/traceability.html. ---
COPY viz/ /app/viz/

# --- Bundled CDISCPILOT01 reference (offline default) + pinned ARS schema +
#     the USDM objective/endpoint fixture the traceability graph needs ---
COPY fixtures/ /app/fixtures/

WORKDIR /workspace
