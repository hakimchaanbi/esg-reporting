#!/usr/bin/env bash
# Download official GRI Standard PDFs from globalreporting.org into standards/gri/.
# These are the primary sources every mapping row must cite. Publicly downloadable;
# attribution to GRI required when quoted.
set -u
cd "$(dirname "$0")"
mkdir -p gri
cd gri

# standard number : globalreporting.org pdf.ashx id
PAIRS="401:12543 403:12565"

for pair in $PAIRS; do
  n="${pair%%:*}"
  id="${pair##*:}"
  out="gri-${n}.pdf"
  echo "-- GRI ${n} (id=${id})"
  curl -sSL --compressed \
       -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36" \
       -H "Accept: application/pdf,*/*" \
       -o "$out" "https://www.globalreporting.org/pdf.ashx?id=${id}"
  echo -n "   $(du -h "$out" | cut -f1)  "
  file -b "$out" | cut -c1-60
  sleep 1.5
done
