#!/usr/bin/env bash
# Ionity Business Mind Map (IBMM) | Ionity Global (Pty) Ltd | AEDI
# Author: Dennis Grobler (Wabakipi) <dennis.g@ionity.digital>
# Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved
#
# Builds the Beta 1 handover package for testers from the committed tree (git archive of HEAD, so nothing
# uncommitted, no data\, models\ or secrets can get in):
#
#   tools/make_beta_package.sh <out-dir> [app-debug.apk]
#
# Writes <out-dir>/IBMM_Beta1_Handover_<date>/ and <out-dir>/IBMM_Beta1_Handover_<date>.zip:
#   README.md, 01_..., 02_..., 03_... (docs/beta, with @COMMIT@ / @DATE@ filled in), tools/setup_ibmm.ps1,
#   tools/collect_logs.ps1, binaries/ (README + the APK if given), source/IBMM (the app without old blueprint
#   copies, build prompts or the superseded POPIA v1.0 report), MANIFEST.txt, SHA256SUMS.txt.
set -euo pipefail
out="${1:?usage: $0 <out-dir> [app-debug.apk]}"
apk="${2:-}"
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

commit="$(git rev-parse --short=7 HEAD)"
commit_date="$(git log -1 --format=%cd --date=format:'%-d %B %Y' HEAD)"
date_iso="${IBMM_PACKAGE_DATE:-$(date +%F)}"
date_long="$(date -d "$date_iso" +'%-d %B %Y')"
name="IBMM_Beta1_Handover_$date_iso"
mkdir -p "$out"
out="$(cd "$out" && pwd)"
pkg="$out/$name"
[ -e "$pkg" ] && { echo "$pkg already exists: remove it or choose another out-dir" >&2; exit 1; }
mkdir -p "$pkg/tools" "$pkg/binaries" "$pkg/source/IBMM"

fill() { sed -e "s/@COMMIT@/$commit/g" -e "s/@COMMIT_DATE@/$commit_date/g" -e "s/@DATE@/$date_long/g" -e "s/@DATE_ISO@/$date_iso/g" "$1" > "$2"; }
fill docs/beta/README.md "$pkg/README.md"
for f in 01_DEPLOYMENT_AND_INSTALLATION.md 02_ABOUT_IBMM_POC_AND_SCOPE.md 03_USER_GUIDE.md; do fill "docs/beta/$f" "$pkg/$f"; done
fill docs/beta/BINARIES.md "$pkg/binaries/README.md"
git show HEAD:tools/setup_ibmm.ps1   > "$pkg/tools/setup_ibmm.ps1"
git show HEAD:tools/collect_logs.ps1 > "$pkg/tools/collect_logs.ps1"
if [ -n "$apk" ]; then
  [ -f "$apk" ] || { echo "APK $apk not found" >&2; exit 1; }
  cp "$apk" "$pkg/binaries/IBMM-android-debug.apk"
fi

git archive --format=tar HEAD -- . \
  ':!NoteCad_Blueprint' ':!NoteCad_Blueprint.zip' ':!NoteCad_phase5.zip' \
  ':!ION-ARC-NOTECAD-2026-001_NoteCad_Master_Blueprint_v1.0.docx' ':!ION-ARC-NOTECAD-2026-001_NoteCad_Master_Blueprint_v1.0.pdf' \
  ':!.claude' ':!docs/prompts' \
  ':!docs/compliance/Ionity_NoteCad_POPIA_Assessment_v1.0.docx' ':!docs/compliance/Ionity_NoteCad_POPIA_Assessment_v1.0.pdf' \
  | tar -x -C "$pkg/source/IBMM"

# a last check: nothing that looks like a key (the one test that asserts a PEM header is allowed)
if grep -rIlE 'sk-ant-[A-Za-z0-9]|NC_BRAIN_DEEPGRAM_KEY=[A-Za-z0-9]{10}|NC_BRAIN_API_TOKEN=[A-Za-z0-9_-]{20}' "$pkg"; then
  echo "something that looks like a key is in the package: stopping" >&2; exit 1
fi

(
  cd "$pkg"
  {
    echo "IBMM Beta 1 handover package - $date_long"
    echo "Source: github.com/dennisGIonity/Ionity_NoteCad_AI main @ $commit ($commit_date)"
    echo "APK: $([ -n "$apk" ] && echo "binaries/IBMM-android-debug.apk" || echo "not included")"
    echo "Policy 986 AED | License AED 900 | (c) 2026 Ionity Global (Pty) Ltd - All rights reserved"
    echo
    echo "Files (bytes, path):"
    find . -type f ! -name MANIFEST.txt ! -name SHA256SUMS.txt | sed 's|^\./||' | LC_ALL=C sort | while read -r f; do
      printf '%10s  %s\n' "$(stat -c %s "$f")" "$f"
    done
  } > MANIFEST.txt
  find . -type f ! -name SHA256SUMS.txt | sed 's|^\./||' | LC_ALL=C sort | xargs -d '\n' sha256sum > SHA256SUMS.txt
)
(cd "$out" && rm -f "$name.zip" && zip -qr -9 "$name.zip" "$name" && unzip -tq "$name.zip" >/dev/null)
echo "built $out/$name.zip ($(du -h "$out/$name.zip" | cut -f1)) from $commit$([ -n "$apk" ] && echo ", with the APK")"
