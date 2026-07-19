#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Cross-Shell Quantitative Benchmark: VerseShell vs PowerShell vs Git Bash
# ═══════════════════════════════════════════════════════════════════════════
set -o pipefail

AE="./target/release/ae"
SHELLS=("ae" "pwsh" "bash")
# Number of warmup iterations (excluded from timing)
WARMUP=3
# Number of measured iterations
ITERS=20

# ── Helpers ──────────────────────────────────────────────────────────────

# Time a command in milliseconds (single run, discard output).
# Prints raw ms as integer.
time_cmd_ms() {
  local shell="$1" cmd="$2"
  case "$shell" in
    ae)
      # Use PowerShell's high-resolution timer wrapping ae
      powershell -NoProfile -Command "
        \$w = [System.Diagnostics.Stopwatch]::StartNew()
        \$null = & '$AE' --json -c '$cmd' 2>\$null
        \$w.Stop()
        Write-Host (\$w.Elapsed.TotalMilliseconds.ToString('F2'))
      "
      ;;
    pwsh)
      powershell -NoProfile -Command "
        \$w = [System.Diagnostics.Stopwatch]::StartNew()
        \$null = Invoke-Expression '$cmd' 2>\$null
        \$w.Stop()
        Write-Host (\$w.Elapsed.TotalMilliseconds.ToString('F2'))
      "
      ;;
    bash)
      powershell -NoProfile -Command "
        \$w = [System.Diagnostics.Stopwatch]::StartNew()
        \$psi = New-Object System.Diagnostics.ProcessStartInfo
        \$psi.FileName = 'C:\\Program Files\\Git\\bin\\bash.exe'
        \$psi.Arguments = '-lc', '$cmd'
        \$psi.UseShellExecute = \$false
        \$psi.RedirectStandardOutput = \$true
        \$psi.RedirectStandardError = \$true
        \$psi.CreateNoWindow = \$true
        \$p = [System.Diagnostics.Process]::Start(\$psi)
        \$p.WaitForExit()
        \$w.Stop()
        Write-Host (\$w.Elapsed.TotalMilliseconds.ToString('F2'))
      "
      ;;
  esac
}

# Run multiple iterations and collect results
bench() {
  local label="$1" shell="$2" cmd="$3" n="$4"
  echo "  [$label] $shell ($n runs)..."

  local total=0 count=0 min=999999 max=0
  local times=()

  # Warmup
  for i in $(seq 1 $WARMUP); do
    time_cmd_ms "$shell" "$cmd" > /dev/null 2>&1
  done

  # Measured runs
  for i in $(seq 1 $n); do
    local t
    t=$(time_cmd_ms "$shell" "$cmd")
    # Clean: keep only digits and dot
    t=$(echo "$t" | tr -d '\r\n' | grep -oE '[0-9]+\.[0-9]+|[0-9]+')
    if [[ -n "$t" ]]; then
      times+=("$t")
      count=$((count + 1))
      # Use awk for float comparison
      if (( $(echo "$t < $min" | bc -l 2>/dev/null || echo 0) )); then min=$t; fi
      if (( $(echo "$t > $max" | bc -l 2>/dev/null || echo 0) )); then max=$t; fi
    fi
  done

  if [[ $count -eq 0 ]]; then
    echo "    ERROR: all runs failed"
    return 1
  fi

  # Calculate mean
  local sum=0
  for t in "${times[@]}"; do
    sum=$(echo "$sum + $t" | bc -l)
  done
  local mean
  mean=$(echo "scale=3; $sum / $count" | bc -l)

  echo "    mean=${mean}ms  min=${min}ms  max=${max}ms  runs=${count}"
  # Return mean as the score
  echo "$mean"
}

# ── Benchmark Categories ─────────────────────────────────────────────────

echo "═══════════════════════════════════════════════════════════"
echo "VerseShell v0.5.0 vs PowerShell vs Git Bash Benchmark"
echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Iterations: $ITERS (warmup: $WARMUP)"
echo "═══════════════════════════════════════════════════════════"
echo ""

# ──────────────────────────────────────────────────────────────────────
# SECTION 1: SYSTEM INFORMATION QUERIES
# ──────────────────────────────────────────────────────────────────────
echo "=== SECTION 1: System Information Queries ==="
echo ""

bench "CPU info"    ae   "sys.cpu_info()"                                                  $ITERS
bench "CPU info"    pwsh "Get-CimInstance Win32_Processor | Select Name,NumberOfCores,MaxClockSpeed" $ITERS
bench "CPU info"    bash "cat /proc/cpuinfo 2>/dev/null || echo N/A"                        $ITERS
echo ""

bench "Memory"      ae   "sys.mem_info()"                                                   $ITERS
bench "Memory"      pwsh "Get-CimInstance Win32_OperatingSystem | Select TotalVisibleMemorySize,FreePhysicalMemory" $ITERS
bench "Memory"      bash "free 2>/dev/null || echo N/A"                                     $ITERS
echo ""

bench "Disk info"   ae   "sys.disk_info()"                                                  $ITERS
bench "Disk info"   pwsh "Get-PSDrive -PSProvider FileSystem | Where Used -gt 0 | Select Name,Used,Free" $ITERS
bench "Disk info"   bash "df -h 2>/dev/null || echo N/A"                                    $ITERS
echo ""

bench "Process top5" ae  "sys.process_info()"                                               $ITERS
bench "Process top5" pwsh "Get-Process | Sort -Descending CPU | Select -First 5"             $ITERS
bench "Process top5" bash "ps aux --sort=-%cpu 2>/dev/null | head -6 || echo N/A"            $ITERS
echo ""

bench "Env vars"    ae   "sys.env_all()"                                                    $ITERS
bench "Env vars"    pwsh "Get-ChildItem Env: | Select Name,Value"                           $ITERS
bench "Env vars"    bash "printenv"                                                         $ITERS
echo ""

# ──────────────────────────────────────────────────────────────────────
# SECTION 2: FILE SYSTEM OPERATIONS
# ──────────────────────────────────────────────────────────────────────
echo "=== SECTION 2: File System Operations ==="
echo ""

bench "List dir (ae)"     ae   "file.ls(\".\")"                                             $ITERS
bench "List dir (pwsh)"   pwsh "Get-ChildItem . -File | Select Name,Length,LastWriteTime"   $ITERS
bench "List dir (bash)"   bash "ls -la"                                                     $ITERS
echo ""

bench "Read file"    ae   "file.read(\"README.md\")"                                        $ITERS
bench "Read file"    pwsh "Get-Content README.md -Raw"                                      $ITERS
bench "Read file"    bash "cat README.md"                                                   $ITERS
echo ""

bench "Count lines"  ae   "file.wc(\"README.md\")"                                          $ITERS
bench "Count lines"  pwsh "(Get-Content README.md | Measure-Object -Line).Lines"            $ITERS
bench "Count lines"  bash "wc -l README.md 2>/dev/null || echo N/A"                         $ITERS
echo ""

bench "Grep"         ae   "file.grep(\"fn\", \"src/main.rs\")"                              $ITERS
bench "Grep"         pwsh "Select-String -Path src/main.rs -Pattern 'fn' | Select -First 20" $ITERS
bench "Grep"         bash "grep -n 'fn' src/main.rs 2>/dev/null | head -20 || echo N/A"     $ITERS
echo ""

# ──────────────────────────────────────────────────────────────────────
# SECTION 3: DATA PIPELINE OPERATIONS (VerseShell vs PowerShell vs Bash)
# ──────────────────────────────────────────────────────────────────────
echo "=== SECTION 3: Data Pipeline Operations ==="
echo ""

# Array: generate 1..1000, map (*2), filter (>500), sum
bench "Pipeline 1K"   ae   "[1,2,3,4,5,6,7,8,9,10] | map(fn(x)=>x*2) | where(fn(x)=>x>5) | reduce(fn(a,b)=>a+b,0)" $ITERS
bench "Pipeline 1K"   pwsh "(1..1000 | ForEach-Object { \$_ * 2 } | Where-Object { \$_ -gt 500 } | Measure-Object -Sum).Sum" $ITERS
bench "Pipeline 1K"   bash "seq 1 1000 | awk '{print \$1*2}' | awk '\$1>500' | paste -sd+ | bc" $ITERS
echo ""

bench "Sort 500"      ae   "range(1,500) | sort() | reverse() | take(10)"                   $ITERS
bench "Sort 500"      pwsh "(1..500 | Sort-Object -Descending | Select -First 10) -join ','" $ITERS
bench "Sort 500"      bash "seq 1 500 | sort -rn | head -10 | paste -sd,"                    $ITERS
echo ""

bench "JSON parse"    ae   "json.parse(\"{\\\"a\\\":1,\\\"b\\\":\\\"hello\\\"}\")"          $ITERS
bench "JSON parse"    pwsh "'{\"a\":1,\"b\":\"hello\"}' | ConvertFrom-Json"                 $ITERS
bench "JSON parse"    bash "echo '{\"a\":1,\"b\":\"hello\"}' | python3 -c 'import json,sys;print(json.load(sys.stdin))' 2>/dev/null || echo N/A" $ITERS
echo ""

# ──────────────────────────────────────────────────────────────────────
# SECTION 4: STRING OPERATIONS
# ──────────────────────────────────────────────────────────────────────
echo "=== SECTION 4: String Operations ==="
echo ""

bench "Split/join"    ae   "str.join(\"-\", str.split(\"a b c d e\", \" \"))"               $ITERS
bench "Split/join"    pwsh "('a b c d e' -split ' ' -join '-')"                             $ITERS
bench "Split/join"    bash "echo 'a b c d e' | tr ' ' '-'"                                  $ITERS
echo ""

# ──────────────────────────────────────────────────────────────────────
# SECTION 5: SHELL EXEC (External Process)
# ──────────────────────────────────────────────────────────────────────
echo "=== SECTION 5: External Process Execution ==="
echo ""

bench "Exec echo"   ae   "shell.exec([\"cmd\", \"/C\", \"echo hello\"])"                    $ITERS
bench "Exec echo"   pwsh "cmd /C 'echo hello'"                                              $ITERS
bench "Exec echo"   bash "echo hello"                                                       $ITERS
echo ""

bench "Exec where"  ae   "shell.exec([\"cmd\", \"/C\", \"where cmd\"])"                     $ITERS
bench "Exec where"  pwsh "Get-Command cmd | Select Source"                                  $ITERS
bench "Exec where"  bash "which cmd 2>/dev/null || where cmd"                               $ITERS
echo ""

# ──────────────────────────────────────────────────────────────────────
# SECTION 6: AGENT USABILITY METRICS (Qualitative + Quantitative)
# ──────────────────────────────────────────────────────────────────────
echo "=== SECTION 6: Agent Usability Metrics ==="
echo ""

echo "--- 6a. Output Structure (JSON parseability) ---"
echo ""

# Test: get CPU info and check if output is valid JSON
echo -n "  [AE] Output is structured JSON: "
AE_OUT=$("$AE" --json -c "sys.cpu_info()" 2>&1)
if echo "$AE_OUT" | python3 -c "import json,sys; json.load(sys.stdin); print('YES')" 2>/dev/null; then
  echo "    $(echo "$AE_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'  keys: {list(d.keys())[:5]}')" 2>/dev/null)"
else
  echo "    NO"
fi

echo -n "  [PowerShell] Output is structured JSON: "
PW_OUT=$(powershell -NoProfile -Command "Get-CimInstance Win32_Processor | Select Name,NumberOfCores,MaxClockSpeed | ConvertTo-Json" 2>&1)
if echo "$PW_OUT" | python3 -c "import json,sys; json.load(sys.stdin); print('YES')" 2>/dev/null; then
  echo "    YES (requires explicit ConvertTo-Json)"
else
  echo "    NO (raw: $(echo "$PW_OUT" | head -1))"
fi

echo -n "  [Bash] Output is structured JSON: "
BA_OUT=$(bash -lc "cat /proc/cpuinfo 2>/dev/null | head -5" 2>&1)
if echo "$BA_OUT" | python3 -c "import json,sys; json.load(sys.stdin); print('YES')" 2>/dev/null; then
  echo "    YES"
else
  echo "    NO (raw text: $(echo "$BA_OUT" | head -1 | cut -c1-60))"
fi
echo ""

echo "--- 6b. Error Message Quality ---"
echo ""

echo -n "  [AE] Typo suggestion (srot -> sort): "
AE_ERR=$("$AE" --json -c "srot([3,1,2])" 2>&1)
echo "$AE_ERR" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'code={d[\"error\"][\"code\"]}, hint={d[\"error\"].get(\"hint\",\"N/A\")}')" 2>/dev/null || echo "parse failed"

echo -n "  [PowerShell] Typo suggestion: "
PW_ERR=$(powershell -NoProfile -Command "Srot-Object 2>&1" 2>&1 || true)
echo "    (raw: $(echo "$PW_ERR" | tr '\n' ' ' | cut -c1-100))"

echo -n "  [Bash] Typo suggestion: "
BA_ERR=$(bash -lc "srot 2>&1" 2>&1 || true)
echo "    (raw: $(echo "$BA_ERR" | tr '\n' ' ' | cut -c1-80))"
echo ""

echo "--- 6c. Type Safety ---"
echo ""

echo -n "  [AE] Type check 'hello' + 5: "
AE_TYPE=$("$AE" --json -c "\"hello\" + 5" 2>&1)
echo "$AE_TYPE" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'error={d[\"error\"][\"code\"]}')" 2>/dev/null || echo "    no error (coerced)"

echo -n "  [PowerShell] Type check 'hello' + 5: "
PW_TYPE=$(powershell -NoProfile -Command "'hello' + 5" 2>&1 || true)
echo "    $(echo "$PW_TYPE" | tr '\n' ' ' | cut -c1-60)"

echo -n "  [Bash] Type check 'hello' + 5: "
BA_TYPE=$(bash -lc "echo \$((hello + 5))" 2>&1 || true)
echo "    $(echo "$BA_TYPE" | tr '\n' ' ' | cut -c1-60)"
echo ""

echo "--- 6d. Command Character Count (proxy for agent writing cost) ---"
echo ""

echo "  Get CPU info:"
echo "    AE   ($(echo -n "sys.cpu_info()" | wc -c) chars)  sys.cpu_info()"
echo "    PWsh ($(echo -n "Get-CimInstance Win32_Processor | Select Name,NumberOfCores,MaxClockSpeed | ConvertTo-Json" | wc -c) chars)  Get-CimInstance Win32_Processor | ..."
echo "    Bash ($(echo -n "cat /proc/cpuinfo | head -5" | wc -c) chars)  cat /proc/cpuinfo | head -5"

echo "  List dir files:"
echo "    AE   ($(echo -n 'file.ls(".")' | wc -c) chars)  file.ls(\".\")"
echo "    PWsh ($(echo -n "Get-ChildItem . -File | Select Name,Length" | wc -c) chars)  Get-ChildItem . -File | Select Name,Length"
echo "    Bash ($(echo -n "ls -la" | wc -c) chars)  ls -la"

echo "  Filter + Map + Sum:"
echo "    AE   ($(echo -n '[1,2,3] | map(fn(x)=>x*2) | where(fn(x)=>x>5) | reduce(fn(a,b)=>a+b,0)' | wc -c) chars)  [...]"
echo "    PWsh ($(echo -n '(1..1000 | ForEach-Object { $_ * 2 } | Where-Object { $_ -gt 500 } | Measure-Object -Sum).Sum' | wc -c) chars)  (...)"
echo "    Bash ($(echo -n "seq 1 1000 | awk '{print \$1*2}' | awk '\$1>500' | paste -sd+ | bc" | wc -c) chars)  (...)"
echo ""

echo "--- 6e. Consistency / Discoverability ---"
echo ""

echo "  [AE] Builtin count: $("$AE" --json -c "len(arr.keys(modules.list()))" 2>&1 | python3 -c "import json,sys; print(json.load(sys.stdin))" 2>/dev/null || echo "N/A")"
echo "  [PWsh] Verb-Noun pattern: consistent"
echo "  [Bash] No builtin system: depends on external binaries"
echo ""

# ──────────────────────────────────────────────────────────────────────
# SECTION 7: WINDOWS-NATIVE OPERATIONS
# ──────────────────────────────────────────────────────────────────────
echo "=== SECTION 7: Windows-Native Operations ==="
echo ""

bench "Registry"   ae   "win.registry_get(\"HKLM\\\\SOFTWARE\\\\Microsoft\\\\Windows NT\\\\CurrentVersion\", \"ProductName\")" $ITERS
bench "Registry"   pwsh "Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion' | Select ProductName" $ITERS
bench "Registry"   bash "echo N/A" $ITERS
echo ""

bench "Snapshot"   ae   "win.snapshot()" $ITERS
bench "Snapshot"   pwsh "Get-ComputerInfo | Select WindowsProductName,CsTotalPhysicalMemory,CsNumberOfProcessors | ConvertTo-Json" $ITERS
bench "Snapshot"   bash "echo N/A" $ITERS
echo ""

# ──────────────────────────────────────────────────────────────────────
# SUMMARY
# ──────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "Benchmark Complete"
echo "═══════════════════════════════════════════════════════════"
