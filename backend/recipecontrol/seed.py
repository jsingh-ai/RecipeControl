"""Seed RecipeControl machine metadata from the selected read-only source adapter."""

from sqlalchemy import select

from recipecontrol.database import SessionLocal
from recipecontrol.models import MachineModel
from recipecontrol.source import get_source_repository


def main() -> None:
    source = get_source_repository()
    with SessionLocal() as session:
        for machine in source.list_machines():
            existing = session.scalar(
                select(MachineModel).where(MachineModel.source_key == machine.key)
            )
            if existing is None:
                session.add(MachineModel(source_key=machine.key, name=machine.name))
            else:
                existing.name = machine.name
        session.commit()


if __name__ == "__main__":
    main()
