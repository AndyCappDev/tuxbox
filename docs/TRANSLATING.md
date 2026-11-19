# Translating the TuxBox GUI

The configuration window can be shown in several languages. English is the
source language: every string in the code is written in English, and the other
languages live in translation catalogs next to it.

Adding a language needs no Python change. Translating one needs no Python
knowledge either.

## Table of Contents

- [How it works](#how-it-works)
- [Adding a language](#adding-a-language)
- [Updating a translation](#updating-a-translation)
- [Translation tools](#translation-tools)
- [What to translate and what to leave alone](#what-to-translate-and-what-to-leave-alone)
- [Testing a translation](#testing-a-translation)
- [Adding translatable strings to the code](#adding-translatable-strings-to-the-code)

## How it works

Strings are translated with [gettext](https://www.gnu.org/software/gettext/),
the standard used by most free software:

```
tuxbox/locale/tuxbox.pot                     template: every English string
tuxbox/locale/fr/LC_MESSAGES/tuxbox.po       French catalog (source text)
tuxbox/locale/fr/LC_MESSAGES/tuxbox.mo       French catalog (compiled, read by gettext)
```

`tuxbox.pot` is generated from the code and never edited by hand. The `.po`
files are what translators work on. The `.mo` files are what the running
program reads, and they ship with the package, so an installed copy carries its
translations.

A string with no translation, or a language with no catalog, falls back to
English. Nothing breaks, so a partial translation is always usable.

The language is chosen in **File → Global Settings → Language**, and stored as
`language = fr` in the `[gui]` section of `~/.config/tuxbox/config.conf`. Left
unset, the window follows the desktop's locale. A language change is applied
the next time the window is opened.

## Adding a language

Say you want to translate the interface into German (`de`).

1. Install gettext if it is not already there:

   ```bash
   sudo apt install gettext     # Debian/Ubuntu/Mint
   sudo dnf install gettext     # Fedora
   sudo pacman -S gettext       # Arch
   ```

2. Create the catalog from the template:

   ```bash
   ./update_translations.sh de
   ```

   This writes `tuxbox/locale/de/LC_MESSAGES/tuxbox.po`.

3. Open that file in a translation editor (see
   [Translation tools](#translation-tools)) and fill in the `msgstr` of each
   entry. Empty entries stay in English, so you can translate a few strings at
   a time and come back later.

4. Compile it and check the result:

   ```bash
   ./update_translations.sh
   ```

   The script merges any new strings from the code into every catalog, then
   compiles them all. It fails on a mismatch in a `%s` placeholder, which is the
   one translation mistake that would crash the window.

5. Run the GUI (see [Testing a translation](#testing-a-translation)), pick your
   language, and check it.

6. Commit the new `.po` and `.mo` files. That is the whole contribution —
   the language then appears by itself in the Language picker, under its code
   (`de`) unless you add a native name to `LANGUAGE_NAMES` in
   `tuxbox/i18n.py`:

   ```python
   LANGUAGE_NAMES = {
       'en': 'English',
       'fr': 'Français',
       'de': 'Deutsch',
   }
   ```

## Updating a translation

When the interface gains or loses strings, refresh the catalogs:

```bash
./update_translations.sh
```

`msgmerge` keeps existing translations, marks the ones whose English text
changed as `fuzzy` (they need a look, they are shown in English until then),
and adds the new ones empty.

## Translation tools

The `.po` format is understood by every translation platform, so use whichever
you prefer:

| Tool | Notes |
| --- | --- |
| [Poedit](https://poedit.net/) | Desktop editor for Linux, Windows and macOS, shows the source line for each string |
| [Weblate](https://weblate.org/) | Web interface, good for teams and review |
| [Crowdin](https://crowdin.com/) | Web interface, free for open source projects |
| [Lokalise](https://lokalise.com/) | Web interface |
| Your editor | `.po` is plain text; edit it by hand if you prefer |

Set your name in the header of the `.po` file (`Last-Translator`) so you get
credit for the work.

## What to translate and what to leave alone

Translate anything a user reads: window titles, labels, buttons, tooltips,
menus, status bar messages, dialogs, the About box.

Leave these as they are:

- **Placeholders** — `%s`, `%(profile)s`, `%(current)s`. Reorder them freely,
  but keep every one of them, spelled exactly the same.
- **Key names** — `Ctrl`, `Alt`, `Super`, `F1`, `Backspace`. They name physical
  keys, as printed on the keyboard.
- **Product and protocol names** — TourBox, TuxBox, GitHub, USB, Bluetooth,
  KDE Plasma, GIMP.
- **Paths, commands and config keys** — `/dev/ttyACM0`, `git pull`,
  `[device]`, `restart_command`.
- **HTML tags** in the About box and in the import warning (`<b>`, `<a href>`).

Two conventions in this catalog:

- The strings marked with `N_()` in the code are table entries that are both
  displayed *and* stored in the configuration file (control names, key names,
  mouse actions). They are translated when displayed. Translate them, and make
  sure no two of them end up identical in your language: they have to stay
  distinct, because that is what tells a profile entry apart.
- A few technical strings in the mapping summaries (`Ctrl+C`, `Scroll Up`) stay
  in English on purpose, like key caps.

Keep the tone of the original: the interface addresses the user with the
polite form in French (*vous*), not the familiar one.

## Testing a translation

Compile, then start the GUI with your language selected:

```bash
./update_translations.sh

# Either pick it in File -> Global Settings -> Language,
# or force it for one run:
./venv/bin/python - <<'EOF'
from tuxbox import i18n
i18n.setup('de')
from tuxbox.gui.main_window import main
main()
EOF
```

Check that:

- labels are not cut off — German and French are longer than English
- no message shows a literal `%s`
- the About box and the import dialog still render with their formatting
- selecting a control, then an action, still saves the mapping you expect

## Adding translatable strings to the code

Wrap the English text in `_()`:

```python
from tuxbox.i18n import _

self.statusBar().showMessage(_("Profile saved"))
QMessageBox.warning(self, _("Save Failed"), _("Check the logs for details."))
title = _("Editing: %s") % (control_name,)
```

Use `%s` placeholders rather than f-strings or concatenation, so translators can
move the value inside their sentence:

```python
# Good: the translator controls the word order
_("Profile '%s' has been saved.") % (name,)

# Bad: the English word order is baked in
f"Profile '{name}' has been saved."
```

Use named placeholders when there is more than one, and pass a dict:

```python
_("Profile '%(profile)s' has been exported to:\n\n%(path)s") % {
    'profile': profile.name, 'path': file_path,
}
```

For text that is stored and displayed later — a module-level table of control
names, for instance — mark it with `N_()` and translate it where it is shown:

```python
CONTROL_DISPLAY_NAMES = {'knob_cw': N_('Knob Clockwise')}

item = QTableWidgetItem(_(CONTROL_DISPLAY_NAMES[control_name]))
```

Finally, regenerate the template and the catalogs:

```bash
./update_translations.sh
```

Never edit `tuxbox/locale/tuxbox.pot` by hand: the next run overwrites it.
