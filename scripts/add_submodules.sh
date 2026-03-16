#!/usr/bin/env bash
set -euo pipefail

# Run from repo root on branch add-third_party-submodules
git submodule add -b main  https://github.com/ssauvageau-/gdms third_party/gdms
git submodule add -b master https://github.com/RobertSkalko/Grim-Dawn-Modding-Tool third_party/Grim-Dawn-Modding-Tool
git submodule add -b main  https://github.com/wr8fdy/yagde third_party/yagde
git submodule add -b main  https://github.com/nbak/grim-save-parser third_party/grim-save-parser
git submodule add -b main  https://github.com/ChrisElison/GDParser third_party/GDParser

git submodule update --init --recursive

# Stage for commit
git add .gitmodules third_party
echo "Now run: git commit -m 'Add third_party submodules tracking upstream branches' && git push origin add-third_party-submodules"
