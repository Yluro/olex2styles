#!/bin/sh
# Copy the Mac's own Trebuchet MS into Olex2's spare "Optane" font slot, so the
# olex2styles skins draw their headings in it on macOS (see etc/skins/macos.phil).
# Olex2's font list only knows Trebuchet by its Windows file name, trebuc.ttf.
# Nothing is redistributed: the fonts are copied from this Mac's system folders.
#
# Usage: sh install-trebuchet.sh /path/to/olex2   (the folder that holds etc/)
set -e
olex2="${1:?usage: sh install-trebuchet.sh /path/to/olex2  (the folder that holds etc/)}"
fonts="$olex2/etc/gui/fonts"
if [ ! -d "$fonts" ]; then
  echo "$fonts not found: give the Olex2 folder that contains etc/" >&2
  exit 1
fi
for dir in /System/Library/Fonts/Supplemental /Library/Fonts "$HOME/Library/Fonts"; do
  if [ -f "$dir/Trebuchet MS.ttf" ] && [ -f "$dir/Trebuchet MS Bold.ttf" ]; then
    cp "$dir/Trebuchet MS.ttf" "$fonts/Optane.ttf"
    cp "$dir/Trebuchet MS Bold.ttf" "$fonts/Optane Bold.ttf"
    echo "Copied Trebuchet MS from $dir into $fonts"
    echo "Restart Olex2, then pick a skin with the macOS add-on, e.g.: skin modern_macos"
    exit 0
  fi
done
echo "Trebuchet MS not found in /System/Library/Fonts/Supplemental, /Library/Fonts or ~/Library/Fonts" >&2
exit 1
