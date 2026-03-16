# Working Database — third_party Submodules

This file summarizes the third_party submodules and which branches they track.

- third_party/gdms
  - URL: https://github.com/ssauvageau-/gdms
  - Language: Java
  - Purpose: Grim Dawn Modding Suite — UI/tools
  - Tracked branch: main
  - License: MIT (see repo LICENSE)

- third_party/Grim-Dawn-Modding-Tool
  - URL: https://github.com/RobertSkalko/Grim-Dawn-Modding-Tool
  - Language: C#
  - Purpose: DBR reader/editor
  - Tracked branch: master
  - License: (see repo LICENSE)

- third_party/yagde
  - URL: https://github.com/wr8fdy/yagde
  - Language: Rust
  - Purpose: Grim Dawn file editor
  - Tracked branch: main
  - License: MIT

- third_party/grim-save-parser
  - URL: https://github.com/nbak/grim-save-parser
  - Language: Rust
  - Purpose: Savefile parser
  - Tracked branch: main
  - License: MIT

- third_party/GDParser
  - URL: https://github.com/ChrisElison/GDParser
  - Language: C#
  - Purpose: Savefile parser / console utilities
  - Tracked branch: main
  - License: MIT

## How we update

Use `git submodule update --remote --merge --recursive` to fetch branch tips for all submodules and merge them into the checked-out submodule trees, then `git add`/`git commit` to record the new pointers in this repository.
