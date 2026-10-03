"""Makes an account a platform admin (or removes it), with a Firebase custom claim. Safer than ADMIN_EMAILS:
only someone with the server's Firebase key can run it.

    python -m app.scripts.set_admin someone@example.com          # make admin
    python -m app.scripts.set_admin someone@example.com --remove # take it away

The person must sign out and in again (or wait up to an hour) for the change to reach their token.
"""

import sys

from firebase_admin import auth

from app.core.firebase import get_firebase_app


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    user = auth.get_user_by_email(args[0], app=get_firebase_app())
    claims = dict(user.custom_claims or {})
    if "--remove" in sys.argv:
        claims.pop("admin", None)
    else:
        claims["admin"] = True
    auth.set_custom_user_claims(user.uid, claims or None, app=get_firebase_app())
    print(f"{user.email}: admin = {claims.get('admin', False)}")


if __name__ == "__main__":
    main()
