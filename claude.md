# Critical Execution & Security Rules for Claude Code

## 0. ZERO-TOLERANCE RULES (STRICTLY ENFORCED)
- **NEVER run inline Python or Node.js commands under ANY circumstances**:
  - ❌ FORBIDDEN: `python -c "..."` or `python3 -c "..."`
  - ❌ FORBIDDEN: `node -e "..."`
- **REQUIRED WORKFLOW for Script Execution**:
  1. Write the Python/Node code to an explicit file inside `.scratch/` (e.g. `.scratch/run_temp.py` or `.scratch/task.js`) using Claude Code's native `Write` or `Edit` tool.
  2. Execute the script via a static relative file reference: `python .scratch/run_temp.py` or `node .scratch/task.js`.
  3. Clean up the script file afterwards if it is no longer needed.
- **NEVER use Shell Parameter Expansions, Loops, or Chained `cd`**:
  - ❌ FORBIDDEN: Shell variable expansions like `$f`, `$var`, `${var}`, `$(cmd)`, `` `cmd` ``
  - ❌ FORBIDDEN: Dynamic wildcards requiring runtime evaluation: `*`, `?`, `[...]`
  - ❌ FORBIDDEN: Shell loops or control structures: `for ... in`, `while`, `until`, `if ... then`
  - ❌ FORBIDDEN: Directory hopping with chaining: `cd <dir> && ...`

---

## 1. Context & Environment Constraints
This environment has `permissions.blockReadsOutsideWorkingDirectories` strictly enabled.
The sandbox shell parser intercepts and prompts the user on ANY command that contains dynamic expansion, inline code, chained directory changes, brace obfuscation, or runtime path computation (`simple_expansion`, `computed at run time`, `Parser skipped input`).

---

## 2. Mandatory Bash Command Rules

### Rule 1: Static & Explicit Paths Only
- All command arguments, directory paths, and file references must be hardcoded, literal strings relative to the project root.
- Do NOT pipe dynamic file lists into commands (e.g., avoid `find . | xargs ...`).
- If batch processing, multi-directory inspections, or complex file filtering are needed, implement the entire workflow inside a Python or Node.js script using `os.walk` or `pathlib`, then run that single static script.

### Rule 2: Temporary Files
- Write all scratchpads, temporary data, and execution scripts strictly inside `.scratch/` under the project root.
- **NEVER** write to OS system temp directories (`C:\Users\...\AppData\Local\Temp`).

### Rule 3: Preferred Built-in Tools Over Shell Commands
- For reading, finding, searching, or editing files, always prioritize Claude Code's native agent tools (`View`, `GlobTool`, `GrepTool`, `Edit`) over raw Bash commands (`cat`, `ls`, `find`, `grep`, `sed`).
- Native tools bypass the shell parser completely while respecting read block boundaries without triggering false-positive security warnings.

### Rule 4: No Chained Directory Changes (`cd`)
- **NEVER** prepend commands with directory hopping (e.g. `cd server && npx ...` or `cd screenshots && python ...`).
- Always execute commands directly from the project root using directory-specific flags or relative paths:
  - For Node/NPM/NPX: use `--prefix` (e.g. `npx --prefix server tsx server/extract_tmp.ts`).
  - For Python: execute from root referencing the file path (e.g. `python screenshots/data_processor.py`).
  - For Git: use `-C` pointing to relative project directory (e.g. `git -C <dir> status`).

### Rule 5: Inspection & Search Rules (`ls` / `find`)
- **NEVER** use bash `for` loops or subshells to inspect multiple folders (e.g. `for d in dir1 dir2; do ls "$d"; done`).
- To list contents of multiple folders simultaneously in shell, pass each explicit path as a separate argument to `ls`:
  `ls -la path/to/dir1 path/to/dir2`
- Avoid raw dynamic `find` commands that evaluate paths at runtime. Prefer Claude Code's built-in tools (`GlobTool` / `GrepTool`), or write a small inspection Python script using `pathlib.Path.rglob()` or `os.walk()`.

### Rule 6: Avoid Complex Multi-Statement Chaining & Piping
- **NEVER** chain multiple statements across different directories or mix top-level execution with pipes that fail AST parsing (avoiding triggers like `Parser skipped input between top-level statements`).
- Split multi-purpose tasks into separate, single-purpose commands, or encapsulate the multi-step pipeline inside a standalone runner script in `.scratch/`.

### Rule 7: No Inline Stream Editors (`sed` / `awk`)
- **NEVER** execute inline text-substitution scripts using `sed` (e.g. `sed -i "..."`) or `awk` to modify/inspect files.
- Use Claude Code's built-in `Edit` / `Write` tool for modifying source files, or write a dedicated Python script that safely reads and rewrites the target file using standard file operations.

### Rule 8: No Braces with Quotes in Shell Arguments (Expansion Obfuscation)
- **NEVER** use brace expansions (e.g. `{file1,file2}`) in Bash commands.
- **NEVER** pass inline JSON strings or dictionary literals containing braces and quotes (e.g. `{"key": "val"}`) as CLI arguments in Bash.
- When structured parameters or configs are required, write them into a `.json` file inside `.scratch/` first and pass the file path, or handle them directly inside the target script.

### Rule 9: Next.js Dynamic Routes Handling
- Folders with bracket naming like `[param]` (e.g. `[accountId]`) are treated as glob characters by the shell parser.
- **NEVER** pass unescaped brackets or use `find`/`ls` directly targeting routes with `[...]`.
- To inspect or list files inside dynamic route folders, use Claude Code's built-in file view tools (`View` / `GlobTool`) instead of raw Bash `find`, or execute a Python script to traverse the directory.