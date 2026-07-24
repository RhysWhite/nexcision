#!/usr/bin/env bash
# Validate a NEXCISION JSON report before allowing downstream analysis.

set -euo pipefail

usage() {
    cat <<'USAGE'
Usage:
  validate_report.sh [OPTIONS] REPORT FILTERED_NEXUS REGION_COUNTS

Options:
  --min-removed N       Require at least N removed matrix rows.
  --exact-removed N     Require exactly N removed matrix rows.
  --fail-on-warnings    Fail when the report contains one or more warnings.
  --nexus FILE          Verify the input NEXUS SHA-256 checksum.
  --regions FILE        Verify the input regions SHA-256 checksum.
  -h, --help            Show this help message.

Zero removed rows are accepted unless --min-removed or --exact-removed says
otherwise. --min-removed and --exact-removed are mutually exclusive.
USAGE
}

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_nonnegative_integer() {
    case "$2" in
        ''|*[!0-9]*) die "$1 must be a non-negative integer; received '$2'." ;;
    esac
}

sha256_file() {
    local file=$1
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum -- "$file" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 -- "$file" | awk '{print $1}'
    elif command -v python3 >/dev/null 2>&1; then
        python3 - "$file" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
digest = hashlib.sha256()
with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
    else
        die "No SHA-256 implementation was found (sha256sum, shasum, or python3)."
    fi
}

json_value() {
    local expression=$1
    local report=$2
    jq -er "$expression" "$report" 2>/dev/null ||
        die "Report is missing an expected field or contains an invalid value: $expression"
}

verify_checksum() {
    local label=$1
    local file=$2
    local expected=$3

    [[ -f "$file" ]] || die "$label file does not exist: $file"
    local observed
    observed=$(sha256_file "$file")
    [[ "$observed" == "$expected" ]] ||
        die "$label checksum mismatch for '$file' (expected $expected; observed $observed)."
}

minimum_removed=''
exact_removed=''
fail_on_warnings=false
nexus_file=''
regions_file=''

while [[ $# -gt 0 ]]; do
    case "$1" in
        --min-removed)
            [[ $# -ge 2 ]] || die "--min-removed requires a value."
            minimum_removed=$2
            shift 2
            ;;
        --exact-removed)
            [[ $# -ge 2 ]] || die "--exact-removed requires a value."
            exact_removed=$2
            shift 2
            ;;
        --fail-on-warnings)
            fail_on_warnings=true
            shift
            ;;
        --nexus)
            [[ $# -ge 2 ]] || die "--nexus requires a file path."
            nexus_file=$2
            shift 2
            ;;
        --regions)
            [[ $# -ge 2 ]] || die "--regions requires a file path."
            regions_file=$2
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            die "Unknown option: $1"
            ;;
        *)
            break
            ;;
    esac
done

[[ $# -eq 3 ]] || {
    usage >&2
    exit 2
}

report=$1
filtered_nexus=$2
region_counts=$3

[[ -f "$report" ]] || die "Report file does not exist: $report"
command -v jq >/dev/null 2>&1 || die "jq is required to parse the JSON report."

if [[ -n "$minimum_removed" && -n "$exact_removed" ]]; then
    die "--min-removed and --exact-removed cannot be used together."
fi
[[ -z "$minimum_removed" ]] || require_nonnegative_integer "--min-removed" "$minimum_removed"
[[ -z "$exact_removed" ]] || require_nonnegative_integer "--exact-removed" "$exact_removed"

software_name=$(json_value '.software.name | select(. == "NEXCISION")' "$report")
software_version=$(json_value '.software.version | select(type == "string" and length > 0)' "$report")

matrix_rows=$(json_value '.results.matrix_rows_read | select(type == "number" and . >= 0 and floor == .)' "$report")
rows_removed=$(json_value '.results.rows_removed | select(type == "number" and . >= 0 and floor == .)' "$report")
rows_kept=$(json_value '.results.rows_kept | select(type == "number" and . >= 0 and floor == .)' "$report")
unparsed_rows=$(json_value '.results.unparsed_rows | select(type == "number" and . >= 0 and floor == .)' "$report")
warning_count=$(json_value '.results.warnings | select(type == "array") | length' "$report")

[[ $((rows_removed + rows_kept)) -eq "$matrix_rows" ]] ||
    die "Inconsistent row totals: removed ($rows_removed) + kept ($rows_kept) != read ($matrix_rows)."
[[ "$unparsed_rows" -le "$rows_kept" ]] ||
    die "Inconsistent unparsed-row count: $unparsed_rows exceeds rows kept ($rows_kept)."

# When NEXCISION reports that it updated a dimension, the before/after values
# should correspond to the observed input and retained row counts.
dimension_updated=$(jq -r '.results.dimension_updated // ""' "$report")
if [[ -n "$dimension_updated" ]]; then
    [[ "$dimension_updated" == "ntax" || "$dimension_updated" == "nchar" ]] ||
        die "Unexpected dimension_updated value: $dimension_updated"
    dimension_before=$(json_value '.results.dimension_before | select(type == "number" and floor == .)' "$report")
    dimension_after=$(json_value '.results.dimension_after | select(type == "number" and floor == .)' "$report")
    [[ "$dimension_before" -eq "$matrix_rows" ]] ||
        die "Updated dimension began at $dimension_before, but $matrix_rows matrix rows were read."
    [[ "$dimension_after" -eq "$rows_kept" ]] ||
        die "Updated dimension ended at $dimension_after, but $rows_kept rows were kept."
fi

if [[ -n "$exact_removed" && "$rows_removed" -ne "$exact_removed" ]]; then
    die "Expected exactly $exact_removed removed row(s); observed $rows_removed."
fi
if [[ -n "$minimum_removed" && "$rows_removed" -lt "$minimum_removed" ]]; then
    die "Expected at least $minimum_removed removed row(s); observed $rows_removed."
fi

if [[ "$warning_count" -gt 0 ]]; then
    if [[ "$fail_on_warnings" == true ]]; then
        jq -r '.results.warnings[] | "NEXCISION warning: \(.)"' "$report" >&2
        die "Report contains $warning_count warning(s)."
    fi
    jq -r '.results.warnings[] | "WARNING: NEXCISION reported: \(.)"' "$report" >&2
fi

filtered_hash=$(json_value '.outputs.filtered_nexus.sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$report")
counts_hash=$(json_value '.outputs.region_counts.sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$report")
verify_checksum "Filtered NEXUS" "$filtered_nexus" "$filtered_hash"
verify_checksum "Region-counts" "$region_counts" "$counts_hash"

if [[ -n "$nexus_file" ]]; then
    nexus_hash=$(json_value '.inputs.nexus.sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$report")
    verify_checksum "Input NEXUS" "$nexus_file" "$nexus_hash"
fi
if [[ -n "$regions_file" ]]; then
    regions_hash=$(json_value '.inputs.regions.sha256 | select(type == "string" and test("^[0-9a-f]{64}$"))' "$report")
    verify_checksum "Input regions" "$regions_file" "$regions_hash"
fi

printf 'Validated %s %s report: %s row(s) read, %s removed, %s kept, %s warning(s).\n' \
    "$software_name" "$software_version" "$matrix_rows" "$rows_removed" "$rows_kept" "$warning_count"
