"""Seed RecipeControl machine metadata from the selected read-only source adapter."""

from recipecontrol.database import SessionLocal
from recipecontrol.services import sync_machine_catalog
from recipecontrol.source import get_source_repository


def main() -> None:
    source = get_source_repository()
    with SessionLocal() as session:
        sync_machine_catalog(session, list(source.list_machines()))
        session.commit()


if __name__ == "__main__":
    main()
