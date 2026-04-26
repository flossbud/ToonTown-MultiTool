#!/usr/bin/env bash
# Test fixture for the contributor-scan regex used in
# .claude/skills/release/SKILL.md (Phase 6).
#
# If you change the PATTERNS variable here, change it in SKILL.md too.

set -e

PATTERNS='claude|anthropic|noreply@anthropic\.com|\bgpt[-0-9]?\b|\bllm\b|\bcodex\b|co-authored-by:'

assert_match() {
    local desc="$1"
    local input="$2"
    if ! echo "$input" | grep -iqE "$PATTERNS"; then
        echo "FAIL (should match): $desc"
        echo "  input: $input"
        exit 1
    fi
}

assert_no_match() {
    local desc="$1"
    local input="$2"
    if echo "$input" | grep -iqE "$PATTERNS"; then
        echo "FAIL (should NOT match): $desc"
        echo "  input: $input"
        echo "  matched as: $(echo "$input" | grep -ioE "$PATTERNS")"
        exit 1
    fi
}

# --- Should match ---
assert_match "coauthor trailer (Claude)"  "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
assert_match "coauthor trailer (any)"     "Co-authored-by: Someone Else <a@b.c>"
assert_match "anthropic mention"          "Generated with the Anthropic SDK"
assert_match "import anthropic"           "import anthropic"
assert_match "claude in comment"          "# Claude wrote this"
assert_match "GPT-4 mention"              "Drafted by GPT-4"
assert_match "bare gpt"                   "see gpt for details"
assert_match "LLM mention"                "uses an LLM under the hood"
assert_match "Codex word"                 "Codex generated the diff"
assert_match "anthropic email"            "noreply@anthropic.com"

# --- Should NOT match ---
assert_no_match "encrypted"               "encrypted message body"
assert_no_match "html escape"             "from html import escape"
assert_no_match "CodexValidator class"    "class CodexValidator:"
assert_no_match "compiler"                "the compiler emits valid IR"
assert_no_match "plain code"              "def calculate(x): return x * 2"

echo "All contributor scan tests passed."
