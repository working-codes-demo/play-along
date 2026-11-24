#!/usr/bin/env bash
# Download the openly licensed demo recordings into songs/ (see CREDITS.md).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p songs
get() { curl -sSfL --retry 4 --retry-delay 3 -A "play-along-demo/0.1" -o "songs/$1" "$2" && echo "songs/$1"; }
for t in "Monkeys Spinning Monkeys" "Fluffing a Duck" "Sneaky Snitch"; do
  get "${t// /_}.mp3" "https://incompetech.com/music/royalty-free/mp3-royaltyfree/${t// /%20}.mp3"
done
get "Chopin_Nocturne_Op9_No2.mp3" "https://upload.wikimedia.org/wikipedia/commons/8/82/Nocturne_in_E_flat_major%2C_Op._9_no._2.mp3"
