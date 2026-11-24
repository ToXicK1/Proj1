"""Operator commands. Run inside the API container: python -m app.cli create-admin --email ... --name ...

create-admin creates the installation's first administrator and prints a temporary password ONCE, to this
terminal only (never to a log). The administrator must change it at first sign-in, then creates everyone else.
"""

import argparse
import sys

from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin", help="create the first administrator")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    admin.add_argument("--organization", default="Organization")
    args = parser.parse_args(argv)

    from app.core.errors import AppError
    from app.organizations.people import create_first_admin

    settings = get_settings()
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        try:
            temp = create_first_admin(db, settings, email=args.email, display_name=args.name,
                                      organization_name=args.organization)
        except AppError as exc:
            print(f"Not created: {exc.message}", file=sys.stderr)
            return 1
        if settings.signup_mode == "shared":  # connect the default AI and set up the departments, as at first sign-up
            from app.bootstrap import prepare_shared_org

            prepare_shared_org(db, settings)
    print(f"Administrator {args.email} created.")
    print(f"Temporary password (shown once; it must be changed at first sign-in): {temp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
