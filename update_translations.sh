#!/usr/bin/env bash
#
# Regenerate the translation template, then merge and compile every catalog.
#
#   ./update_translations.sh        refresh tuxbox.pot, merge it into the
#                                   existing catalogs and compile them
#   ./update_translations.sh de     same, and create tuxbox/locale/de from the
#                                   template if it does not exist yet
#
# Requires gettext (xgettext, msgmerge, msgfmt). On Debian/Ubuntu:
#   sudo apt install gettext
#
set -euo pipefail
cd "$(dirname "$0")"

DOMAIN=tuxbox
LOCALE_DIR=tuxbox/locale
TEMPLATE="$LOCALE_DIR/$DOMAIN.pot"
VERSION=$(python3 -c 'import tuxbox; print(tuxbox.VERSION)')

if ! command -v xgettext >/dev/null; then
    echo "xgettext not found - install gettext first." >&2
    exit 1
fi

echo "Extracting translatable strings from the GUI ..."
xgettext \
    --language=Python \
    --from-code=UTF-8 \
    --add-comments=Translators \
    --package-name=TuxBox \
    --package-version="$VERSION" \
    --keyword=_ \
    --keyword=N_ \
    --keyword=ngettext:1,2 \
    --output="$TEMPLATE" \
    tuxbox/gui/*.py tuxbox/profile_io.py

# A language asked for on the command line starts from the template.
if [ "$#" -ge 1 ]; then
    for lang in "$@"; do
        po="$LOCALE_DIR/$lang/LC_MESSAGES/$DOMAIN.po"
        if [ -f "$po" ]; then
            echo "Catalog $lang already exists - updating it instead."
        else
            mkdir -p "$(dirname "$po")"
            msginit --no-translator --locale="$lang" --input="$TEMPLATE" --output-file="$po"
            echo "Created $po - translate it, then run this script again."
        fi
    done
fi

shopt -s nullglob
catalogs=("$LOCALE_DIR"/*/LC_MESSAGES/"$DOMAIN".po)
if [ "${#catalogs[@]}" -eq 0 ]; then
    echo "No catalog to update yet. Run '$0 <language>' to create one." >&2
    exit 0
fi

for po in "${catalogs[@]}"; do
    msgmerge --quiet --update --backup=none "$po" "$TEMPLATE"
    msgfmt --check --output-file="${po%.po}.mo" "$po"
    echo "Compiled ${po%.po}.mo"
done
