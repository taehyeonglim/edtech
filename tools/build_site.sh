#!/usr/bin/env bash
# Build the public Pages candidate in a directory that can be audited locally.
set -euo pipefail

if [ "$#" -gt 1 ]; then
  echo "Usage: $0 [output-directory]" >&2
  exit 2
fi

output_dir=${1:-_site}

rm -rf "$output_dir"
mkdir -p "$output_dir"

python3 -m mkdocs build --strict --site-dir "$output_dir/book"
cp index.html "$output_dir/index.html"
touch "$output_dir/.nojekyll"
cp -r chapters "$output_dir/chapters"
cp -r assets "$output_dir/assets"
mkdir -p "$output_dir/book/text"
cp -r book/text/. "$output_dir/book/text/"
