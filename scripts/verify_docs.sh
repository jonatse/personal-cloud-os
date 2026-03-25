#!/bin/bash
#
# Documentation Verification Script for Deploy Pipeline
# Verifies that documentation accurately reflects current implementation
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$PROJECT_ROOT/src"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0
PASSED=0
TOTAL=0

usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Documentation verification for deploy pipeline.

OPTIONS:
    -a, --all           Run all checks (default)
    -v, --version       Check version consistency
    -g, --goals         Verify GOALS.md items
    -r, --readme        Verify README.md
    -i, --impl          Verify implementation files
    -s, --smoke         Run smoke tests (import checks)
    -h, --help          Show this help message

Exit codes:
    0 - All checks passed
    1 - One or more checks failed
EOF
    exit 0
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
}

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_section() {
    echo ""
    echo "=============================================="
    echo " $1"
    echo "=============================================="
}

check_version() {
    log_section "Version Consistency Check"
    
    local version_file="$SRC_DIR/core/version.py"
    local version
    
    if [[ -f "$version_file" ]]; then
        version=$(grep -oP '__version__\s*=\s*"\K[^"]+' "$version_file" 2>/dev/null || echo "")
        
        if [[ -n "$version" ]]; then
            log_pass "version.py exists and contains version: $version"
            
            if grep -q "1.3.1" "$PROJECT_ROOT/README.md" 2>/dev/null; then
                log_pass "README.md references same version"
            else
                log_info "README.md does not reference specific version (acceptable)"
            fi
        else
            log_fail "version.py exists but version not found"
        fi
    else
        log_fail "version.py not found at $version_file"
    fi
}

check_goals() {
    log_section "GOALS.md Verification"
    
    local goals_file="$PROJECT_ROOT/GOALS.md"
    
    if [[ ! -f "$goals_file" ]]; then
        log_fail "GOALS.md not found"
        return
    fi
    
    log_pass "GOALS.md exists"
    
    if grep -q "P1.5.1 Identity CLI" "$goals_file"; then
        log_pass "P1.5.1 Identity CLI section found"
        
        local identity_cmds=("identity create" "identity show" "identity show-qr" "identity export" "identity import")
        for cmd in "${identity_cmds[@]}"; do
            if grep -q "$cmd" "$goals_file"; then
                log_pass "GOALS.md mentions: $cmd"
            else
                log_fail "GOALS.md missing: $cmd"
            fi
        done
    else
        log_fail "P1.5.1 Identity CLI section not found"
    fi
    
    if grep -q "P1.5.3 Circle management" "$goals_file"; then
        log_pass "P1.5.3 Circle management section found"
        
        local circle_cmds=("circle create" "circle list" "circle add" "circle remove")
        for cmd in "${circle_cmds[@]}"; do
            if grep -q "$cmd" "$goals_file"; then
                log_pass "GOALS.md mentions: $cmd"
            else
                log_fail "GOALS.md missing: $cmd"
            fi
        done
    else
        log_fail "P1.5.3 Circle management section not found"
    fi
    
    if grep -q "\[x\] P1.5.1" "$goals_file"; then
        log_pass "P1.5.1 marked as completed in GOALS.md"
    else
        log_fail "P1.5.1 not marked as completed"
    fi
    
    if grep -q "\[x\] P1.5.3" "$goals_file"; then
        log_pass "P1.5.3 marked as completed in GOALS.md"
    else
        log_fail "P1.5.3 not marked as completed"
    fi
}

check_readme() {
    log_section "README.md Verification"
    
    local readme_file="$PROJECT_ROOT/README.md"
    local commands_file="$SRC_DIR/cli/commands.py"
    
    if [[ ! -f "$readme_file" ]]; then
        log_fail "README.md not found"
        return
    fi
    
    log_pass "README.md exists"
    
    if grep -q "What Works Right Now" "$readme_file"; then
        log_pass "README.md has 'What Works Right Now' section"
    else
        log_fail "README.md missing 'What Works Right Now' section"
    fi
    
    local readme_cmds=("help" "status" "peers" "network" "device" "sync" "identity" "circle")
    for cmd in "${readme_cmds[@]}"; do
        if grep -qi "| *${cmd} *" "$readme_file"; then
            log_pass "README.md CLI table mentions: $cmd"
        else
            log_fail "README.md CLI table missing: $cmd"
        fi
    done
    
    if [[ -f "$commands_file" ]]; then
        log_pass "commands.py exists for CLI verification"
        
        for cmd in "${readme_cmds[@]}"; do
            if grep -q "'$cmd':" "$commands_file"; then
                log_pass "commands.py implements: $cmd"
            else
                log_fail "commands.py missing: $cmd"
            fi
        done
    else
        log_fail "commands.py not found"
    fi
    
    if grep -q "Identity-based access control" "$readme_file"; then
        if grep -q "In Progress" "$readme_file"; then
            log_pass "README.md correctly shows access control as In Progress"
        else
            log_fail "README.md access control status unclear"
        fi
    else
        log_fail "README.md missing access control entry"
    fi
}

check_implementation() {
    log_section "Implementation Verification"
    
    local identity_file="$SRC_DIR/core/identity.py"
    local access_control_file="$SRC_DIR/core/access_control.py"
    local commands_file="$SRC_DIR/cli/commands.py"
    
    if [[ -f "$identity_file" ]]; then
        log_pass "identity.py exists"
        
        if grep -q "class IdentityManager" "$identity_file"; then
            log_pass "IdentityManager class found"
        else
            log_fail "IdentityManager class not found"
        fi
        
        local identity_methods=("load_or_create_identity" "get_identity_hash" "export_identity" "import_identity" "list_circles" "create_circle" "get_trust_level")
        for method in "${identity_methods[@]}"; do
            if grep -q "def $method" "$identity_file"; then
                log_pass "identity.py has method: $method"
            else
                log_fail "identity.py missing method: $method"
            fi
        done
    else
        log_fail "identity.py not found"
    fi
    
    if [[ -f "$access_control_file" ]]; then
        log_pass "access_control.py exists"
        
        if grep -q "class AccessControl" "$access_control_file"; then
            log_pass "AccessControl class found"
        else
            log_fail "AccessControl class not found"
        fi
        
        if grep -q "def check_access" "$access_control_file"; then
            log_pass "check_access method found"
        else
            log_fail "check_access method not found"
        fi
    else
        log_fail "access_control.py not found"
    fi
    
    if [[ -f "$commands_file" ]]; then
        log_pass "commands.py exists"
        
        if grep -q "def cmd_identity" "$commands_file"; then
            log_pass "cmd_identity command found"
        else
            log_fail "cmd_identity command not found"
        fi
        
        if grep -q "def cmd_circle" "$commands_file"; then
            log_pass "cmd_circle command found"
        else
            log_fail "cmd_circle command not found"
        fi
    else
        log_fail "commands.py not found"
    fi
}

check_smoke() {
    log_section "Smoke Tests"
    
    local py_paths=(
        "core.version"
        "core.identity"
        "core.access_control"
        "cli.commands"
    )
    
    for module in "${py_paths[@]}"; do
        if (cd "$SRC_DIR" && python3 -c "import $module" 2>/dev/null); then
            log_pass "Module imports: $module"
        else
            log_fail "Module import failed: $module"
        fi
    done
}

run_all_checks() {
    check_version
    check_goals
    check_readme
    check_implementation
    check_smoke
}

SHOW_ALL=false
SHOW_VERSION=false
SHOW_GOALS=false
SHOW_README=false
SHOW_IMPL=false
SHOW_SMOKE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        -a|--all)
            SHOW_ALL=true
            shift
            ;;
        -v|--version)
            SHOW_VERSION=true
            shift
            ;;
        -g|--goals)
            SHOW_GOALS=true
            shift
            ;;
        -r|--readme)
            SHOW_README=true
            shift
            ;;
        -i|--impl)
            SHOW_IMPL=true
            shift
            ;;
        -s|--smoke)
            SHOW_SMOKE=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

if [[ "$SHOW_ALL" == "false" && "$SHOW_VERSION" == "false" && "$SHOW_GOALS" == "false" && "$SHOW_README" == "false" && "$SHOW_IMPL" == "false" && "$SHOW_SMOKE" == "false" ]]; then
    SHOW_ALL=true
fi

if [[ "$SHOW_ALL" == "true" || "$SHOW_VERSION" == "true" ]]; then
    check_version
fi

if [[ "$SHOW_ALL" == "true" || "$SHOW_GOALS" == "true" ]]; then
    check_goals
fi

if [[ "$SHOW_ALL" == "true" || "$SHOW_README" == "true" ]]; then
    check_readme
fi

if [[ "$SHOW_ALL" == "true" || "$SHOW_IMPL" == "true" ]]; then
    check_implementation
fi

if [[ "$SHOW_ALL" == "true" || "$SHOW_SMOKE" == "true" ]]; then
    check_smoke
fi

log_section "Summary"
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo -e "Total:  $TOTAL"

if [[ $FAILED -gt 0 ]]; then
    echo ""
    echo -e "${RED}VERIFICATION FAILED${NC}"
    exit 1
else
    echo ""
    echo -e "${GREEN}ALL CHECKS PASSED${NC}"
    exit 0
fi