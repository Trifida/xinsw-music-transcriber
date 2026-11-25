#!/usr/bin/env python3
"""Publish one immutable private GitHub commit archive to the configured bucket.

Usage:
  MUSICMASTER_GITHUB_READ_TOKEN=... \
  MUSICMASTER_GITHUB_REPOSITORY=owner/repo \
  python scripts/publish_worker_bundle.py <40-character-commit-sha>

Run on the trusted API host only. Never run this command on a GPU worker.
"""
from __future__ import annotations

import argparse
import json
import sys

from musicmaster.cloud.source_bundle import GitHubSourceBundlePublisher, SourceBundleError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("commit_sha", help="Full 40-character Git commit SHA to pin.")
    args = parser.parse_args()
    try:
        published = GitHubSourceBundlePublisher().publish(args.commit_sha)
    except (ValueError, SourceBundleError) as exc:
        print(f"Bundle publish failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(published.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
