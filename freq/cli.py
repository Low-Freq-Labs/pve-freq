"""Early program selection; selecting a command never issues authority.

The dedicated cluster-pilot program currently refuses before legacy project
imports, config/bootstrap, plugins, logging and background workers. It cannot
fall back to ordinary serve. Ordinary commands retain the preserved legacy
implementation; this split does not exclude other processes or direct APIs.
"""
import sys


def main(argv=None):
    values = sys.argv if argv is None else argv
    if type(values) not in (list, tuple):
        return 64
    if any(type(value) is not str for value in values):
        return 64
    check = values[1:] if argv is None else values
    # Reserve this spelling anywhere, before legacy --version or parsing.
    # Misplaced flags/extra arguments cannot cause a legacy loader fallback.
    if 'cluster-pilot' in check:
        if len(check) != 1:
            return 64
        from freq.cluster_pilot_entry import main as selected_main
        return selected_main()
    from freq._legacy_cli import main as legacy_main
    return legacy_main(argv)


def _build_parser():
    """Explicit compatibility for existing TUI imports; ordinary legacy only."""
    from freq._legacy_cli import _build_parser as legacy_build_parser
    return legacy_build_parser()
