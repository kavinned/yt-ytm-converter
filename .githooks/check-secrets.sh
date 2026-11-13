#!/usr/bin/env sh
set -eu

FORBIDDEN_RE='(^|/)(\.env(\..+)?|[^/]*browser[^/]*\.json|headers_auth\.json|oauth[^/]*\.json|[^/]*cookies[^/]*\.txt|[^/]+\.(cookie|cookies|pem|key|p12|pfx)|snapshot-[^/]+\.json|state-[^/]+\.json|preview-[^/]+\.(csv|html))$'
SECRET_RE='SAPISIDHASH|(SAPISID|__Secure-3PAPISID|__Secure-1PAPISID|HSID|SSID|APISID)=|"(cookie|authorization|x-goog-visitor-id)"[[:space:]]*:[[:space:]]*"[^"]{16,}"|AIza[0-9A-Za-z_-]{35}|(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})|sk-[A-Za-z0-9_-]{20,}|-----BEGIN ([A-Z]+ )?PRIVATE KEY-----'

check_filenames() {
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        case "$f" in
            .env.example|*/.env.example) continue ;;
        esac
        if printf '%s\n' "$f" | grep -iqE "$FORBIDDEN_RE"; then
            echo "BLOCKED: sensitive or generated file cannot be committed/pushed: $f" >&2
            return 1
        fi
    done
}

check_diff_stream() {
    # Scan only added lines (excluding +++ file headers) for secret patterns.
    if grep -E '^\+' | grep -vE '^\+\+\+ ' | grep -iqE -m1 "$SECRET_RE"; then
        echo "BLOCKED: potential secret/cookie/credential detected in diff." >&2
        return 1
    fi
}

mode="${1:-}"
case "$mode" in
    staged)
        git diff --cached --name-only --diff-filter=ACMR | check_filenames
        git diff --cached -U0 --diff-filter=ACMR -- ':!.githooks/*' | check_diff_stream
        ;;
    commit)
        c="${2:?missing commit sha}"
        git diff-tree --no-commit-id --name-only -r --diff-filter=ACMR "$c" | check_filenames
        git diff-tree -p -U0 --diff-filter=ACMR "$c" -- ':!.githooks/*' | check_diff_stream
        ;;
    *)
        echo "Usage: $0 {staged|commit <sha>}" >&2
        exit 2
        ;;
esac
