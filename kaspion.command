#!/usr/bin/env bash
# kaspion — macOS. Double-click to open the dashboard.
# The server prints its address and opens your browser; close this window to stop it.
set -euo pipefail
cd "$(dirname "$0")"

# .tools/uv is the installed layout; a plain .venv is a developer checkout — both can
# serve, and the dashboard's start button opens this file either way.
if [ -x ".tools/uv" ] && [ -d ".venv" ]; then
  RUN=(./.tools/uv run python)
elif [ -x ".venv/bin/python" ]; then
  RUN=(.venv/bin/python)
else
  echo "כספיון עדיין לא הותקן."
  echo "לחצו פעמיים על install (באותה תיקייה) והריצו שוב."
  echo
  read -r -p "הקישו Enter לסגירה"
  exit 1
fi

# A browser cannot start a process, but it can open a URL. This builds the kaspion://
# handler behind the dashboard's "הפעילו את כספיון" button, on launch if missing, so
# installs made before that button existed heal themselves.
#
# osacompile, not a hand-written .app: LaunchServices refuses to launch a bundle whose
# executable is a shell script (-10669), while an osacompile applet carries Apple's own
# signed binary. The applet finds this folder from its own location at run time, so
# moving or renaming the kaspion folder cannot leave a handler pointing at nothing.
APP="Kaspion.app"
if [ ! -d "$APP" ]; then
  osacompile -o "$APP" -e 'on open location u
	set a to quoted form of POSIX path of (path to me)
	do shell script "open \"$(dirname " & a & ")/kaspion.command\""
end open location' \
  && /usr/libexec/PlistBuddy \
      -c 'Add :CFBundleURLTypes array' \
      -c 'Add :CFBundleURLTypes:0:CFBundleURLName string Kaspion' \
      -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes array' \
      -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string kaspion' \
      "$APP/Contents/Info.plist" >/dev/null \
  && LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
  && [ -x "$LSREG" ] && "$LSREG" -f "$PWD/$APP" >/dev/null 2>&1 \
  || true  # a failure here costs the button, never the dashboard; without this `|| true`
           # set -e kills the launcher on the LAST command of the chain and never execs
fi

exec "${RUN[@]}" -m kaspion.serve
