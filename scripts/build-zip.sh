#!/usr/bin/env bash
# Build the plugin zip for plugins.qgis.org from a tag, reproducibly:
# the archive holds exactly the tagged tree of airdress_qgis/ plus LICENSE,
# with fixed timestamps and order, so the same tag gives the same bytes.
#
#   scripts/build-zip.sh v0.1.0   →  dist/airdress_qgis-0.1.0.zip
set -euo pipefail
tag="${1:?usage: build-zip.sh <tag>}"
version="${tag#v}"
grep -qx "version=${version}" <(git show "${tag}:airdress_qgis/metadata.txt") \
  || { echo "metadata.txt version does not match ${tag}" >&2; exit 1; }
mkdir -p dist
out="dist/airdress_qgis-${version}.zip"
# git archive writes the commit time as every entry's mtime; LICENSE is
# placed inside the plugin folder, where the plugin repository looks for it.
git archive --format=zip --prefix=airdress_qgis/ -o "${out}.tmp" "${tag}:airdress_qgis"
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
git show "${tag}:LICENSE" > "${tmp}/LICENSE"
(cd "${tmp}" && mkdir airdress_qgis && mv LICENSE airdress_qgis/ \
  && touch -d "@$(git -C "${OLDPWD}" log -1 --format=%ct "${tag}")" airdress_qgis/LICENSE \
  && TZ=UTC zip -X -q "${OLDPWD}/${out}.tmp" airdress_qgis/LICENSE)
mv "${out}.tmp" "${out}"
sha256sum "${out}"
