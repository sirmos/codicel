"""Regression tests for the analyzer's evidence and filtering safeguards."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


# ``analyze.py`` is run as a backend module by the application and uses
# sibling imports (``from ingest import ...``), so make that directory
# importable when this test is invoked from the repository root.
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import analyze
from ingest import CommitRecord


def commit(sha: str, files: list[str]) -> CommitRecord:
    return CommitRecord(
        sha=sha,
        author="Test Author",
        date="2025-01-01T00:00:00+00:00",
        message="Test change",
        files_changed=files,
    )


def sha(number: int) -> str:
    """Produce a 40-character SHA with a distinct abbreviated prefix."""
    return f"{number:010x}" + "0" * 30


def fake_client(payload: dict) -> SimpleNamespace:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **_: response)
        )
    )


class NarrateErasTests(unittest.TestCase):
    def test_eras_without_valid_evidence_citations_are_not_returned(self) -> None:
        commits = [commit(sha(number), ["src/app.py"]) for number in range(1, 4)]
        client = fake_client(
            {"eras": [{"title": "Unsupported", "evidence_shas": []}]}
        )

        with patch.object(analyze, "_get_client", return_value=client):
            findings = analyze.narrate_eras({"src": commits})

        self.assertEqual(findings, [])

    def test_overlapping_commits_produce_one_era_finding(self) -> None:
        # Each cross-cutting commit touches both modules. cluster_eras assigns
        # it to its first/primary module, so it is narrated only once.
        commits = [
            commit(sha(number), ["src/app.py", "docs/architecture.md"])
            for number in range(1, 4)
        ]
        clusters = analyze.cluster_eras(commits)
        self.assertEqual(set(clusters), {"src"})

        client = fake_client(
            {
                "eras": [
                    {
                        "title": "Cross-cutting migration",
                        "evidence_shas": [item.sha[:10] for item in commits],
                    }
                ]
            }
        )
        with patch.object(analyze, "_get_client", return_value=client):
            findings = analyze.narrate_eras(clusters)

        self.assertEqual(len(findings), 1)
        self.assertEqual(
            {evidence.commit_sha for evidence in findings[0].evidence},
            {item.sha for item in commits},
        )


class DeadCodeCandidateTests(unittest.TestCase):
    def test_dot_folder_files_are_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative_path, content in {
                ".github/workflow_helper.py": "def githubOnlyHelper(): pass\n",
                ".agents/agent_helper.py": "def agentOnlyHelper(): pass\n",
                "src/application.py": "def applicationHelper(): pass\n",
            }.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)

            candidates = analyze.find_dead_code_candidates(
                str(root),
                [
                    ".github/workflow_helper.py",
                    ".agents/agent_helper.py",
                    "src/application.py",
                ],
            )

        self.assertEqual(candidates, [{"name": "applicationHelper", "file": "src/application.py"}])
