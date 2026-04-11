"""Regression tests for internal documentation links.

Proves: every markdown link in public-facing docs resolves to an
existing file. Catches dead links after file renames or deletions.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

# Public-facing markdown files that users read
PUBLIC_DOCS = [
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CHANGELOG.md",
    "docs/API-REFERENCE.md",
    "docs/CLI-REFERENCE.md",
    "docs/CONFIGURATION.md",
    "docs/QUICK-REFERENCE.md",
]


class TestInternalLinksResolve(unittest.TestCase):
    """Every [text](path.md) link must resolve to an existing file."""

    def test_all_md_links_resolve(self):
        """Markdown file links must point to existing files."""
        broken = []
        for doc in PUBLIC_DOCS:
            doc_path = os.path.join(REPO_ROOT, doc)
            if not os.path.isfile(doc_path):
                continue
            doc_dir = os.path.dirname(doc_path)
            with open(doc_path) as f:
                content = f.read()
            # Match [text](path) but not URLs (http/https) or anchors (#)
            for m in re.finditer(r'\[([^\]]*)\]\(([^)]+)\)', content):
                target = m.group(2)
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                # Strip anchor from path (e.g., "file.md#section")
                file_target = target.split("#")[0]
                if not file_target:
                    continue
                # Resolve relative to doc's directory
                full_path = os.path.normpath(os.path.join(doc_dir, file_target))
                if not os.path.exists(full_path):
                    broken.append(f"{doc}: [{m.group(1)}]({target}) -> {full_path}")

        self.assertEqual(broken, [],
                         f"Broken internal links:\n" + "\n".join(broken))

    def test_readme_anchor_links_resolve(self):
        """README anchor links must have matching headings."""
        readme_path = os.path.join(REPO_ROOT, "README.md")
        with open(readme_path) as f:
            content = f.read()

        # Collect all headings as anchors (GitHub-style: lowercase, hyphens)
        headings = set()
        for m in re.finditer(r"^#+\s+(.+)$", content, re.MULTILINE):
            anchor = m.group(1).lower().strip()
            anchor = re.sub(r"[^\w\s-]", "", anchor)
            anchor = re.sub(r"\s+", "-", anchor)
            headings.add(anchor)

        # Check all anchor links
        broken = []
        for m in re.finditer(r'\[([^\]]*)\]\((#[^)]+)\)', content):
            anchor = m.group(2)[1:]  # Strip leading #
            if anchor not in headings:
                broken.append(f"[{m.group(1)}](#{anchor})")

        self.assertEqual(broken, [],
                         f"Broken anchor links in README:\n" + "\n".join(broken))


class TestPublicDocsExist(unittest.TestCase):
    """All public docs referenced from README must exist."""

    def test_all_public_docs_exist(self):
        missing = [d for d in PUBLIC_DOCS
                   if not os.path.isfile(os.path.join(REPO_ROOT, d))]
        self.assertEqual(missing, [],
                         f"Public docs missing: {missing}")


if __name__ == "__main__":
    unittest.main()
