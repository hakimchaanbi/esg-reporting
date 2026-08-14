#!/usr/bin/env bash
# Pull the disclosure inventory out of each downloaded GRI Standard PDF.
# Output: standards/gri/gri-<n>.txt (full text) and a printed disclosure list.
set -u
cd "$(dirname "$0")/gri"

for pdf in gri-*.pdf; do
  base="${pdf%.pdf}"
  pdftotext -layout "$pdf" "$base.txt"
  echo "########## $base ##########"
  grep -oE "Disclosure [0-9]{3}-[0-9]+ [A-Za-z][^|]{0,80}" "$base.txt" \
    | sed 's/  */ /g' | sort -u | head -30
  echo
done
