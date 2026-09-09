"""Ids of the bundled example missions, for tests to refer to.

Named *here*, not in the application: the example backend discovers whatever
mission files it finds in `src/audit_front/example_data/`, so these ids are a
property of the fixtures rather than of the code under test. Renaming or
removing a mission file fails once, loudly, in `test_example_data.py`.

The two are chosen because they take opposite paths through the pipeline, so
most behaviour is worth exercising against both.
"""

from __future__ import annotations

# Sparse mission: no loss events, no registered methodology, no prior
# recommendations. Reproduces the sample output that shaped the UI.
AYVENS_UK = "26-IRB/AYVENS-019"

# Populated mission: loss events, a matched methodology, prior recommendations
# and adverse 3LOD reporting.
AYVENS_DE = "26-IRB/AYVENS-021"

SAMPLE_MISSIONS = (AYVENS_UK, AYVENS_DE)
