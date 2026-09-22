from __future__ import annotations

from pathlib import Path
import shutil
import sys

DATA_PROVIDER = Path("backend/app/data/dataProvider.py")


def backup(path: Path) -> None:
    target = path.with_suffix(path.suffix + ".phase4-slice1-backup")
    if not target.exists():
        shutil.copy2(path, target)


def main() -> int:
    if not DATA_PROVIDER.is_file():
        print(
            "Run this script from the StoryStudio repository root after "
            "Phase 3 closure.",
            file=sys.stderr,
        )
        return 2

    text = DATA_PROVIDER.read_text(encoding="utf-8")
    original = text

    import_line = (
        "from app.data.batchGenerationRepository import "
        "BatchGenerationRepository\n"
    )
    if import_line not in text:
        markers = (
            "from app.data.runtimeRepository import RuntimeRepository\n",
            "from app.data.lifecycleRepository import LifecycleRepository\n",
            "from app.data.worldRepository import WorldRepository\n",
            "from app.data.workflowRepository import WorkflowRepository\n",
        )
        marker = next(
            (candidate for candidate in markers if candidate in text),
            None,
        )
        if marker is None:
            raise RuntimeError(
                "Could not find a DataProvider repository import marker"
            )
        text = text.replace(marker, marker + import_line, 1)

    if "self.batch_generation = BatchGenerationRepository(db)" not in text:
        markers = (
            "        self.runtime = RuntimeRepository(db)\n",
            "        self.lifecycle = LifecycleRepository(db)\n",
            "        self.world = WorldRepository(db)\n",
            "        self.workflows = WorkflowRepository(db)\n",
        )
        marker = next(
            (candidate for candidate in markers if candidate in text),
            None,
        )
        if marker is None:
            raise RuntimeError(
                "Could not find a DataProvider repository constructor marker"
            )
        text = text.replace(
            marker,
            marker
            + "        self.batch_generation = "
              "BatchGenerationRepository(db)\n",
            1,
        )

    if text != original:
        backup(DATA_PROVIDER)
        DATA_PROVIDER.write_text(text, encoding="utf-8")
        print(f"Updated {DATA_PROVIDER}")
    else:
        print("DataProvider already contains Phase 4 Slice 1 wiring.")

    print("Phase 4 Slice 1 integration applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
