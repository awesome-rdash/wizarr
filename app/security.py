from datetime import datetime, timedelta, timezone
from functools import wraps
from logging import info
from os import getenv

from flask import make_response, redirect, render_template, request
from flask_jwt_extended import (create_access_token, get_jti, get_jwt,
                                get_jwt_identity, set_access_cookies,
                                verify_jwt_in_request)
from playhouse.shortcuts import model_to_dict

from models import Sessions, Settings
from models.database.accounts import Accounts

# Yh this code looks messy but it works so ill tidy it up later

def server_verified():
    server_verified = Settings.get_or_none(Settings.key == "server_verified")
    return True if server_verified and server_verified.value == "True" else False

# Generate a secret key, and store it in root/database/secret.key if it doesn't exist, return the secret key
def secret_key(length: int = 32) -> str:
    from os import mkdir, path
    from secrets import token_hex

    from app import BASE_DIR

    # Check if the database directory exists
    if not path.exists("database"):
        mkdir("database")

    # Check if the secret key file exists
    if not path.exists(path.join(BASE_DIR, "../", "database/secret.key")):
        # Generate a secret key and write it to the secret key file
        with open(path.join(BASE_DIR, "../", "database/secret.key"), "w") as f:
            secret_key = token_hex(length)
            f.write(secret_key)
            return secret_key

    # Read the secret key from the secret key file
    with open(path.join(BASE_DIR, "../", "database/secret.key"), "r") as f:
        secret_key = f.read()

    return secret_key

def refresh_expiring_jwts(response):
    try:
        jwt = get_jwt()
        if datetime.timestamp(datetime.now(timezone.utc) + timedelta(minutes=30)) > jwt["exp"]:
            access_token = create_access_token(identity=get_jwt_identity())
            Sessions.update(session=get_jti(access_token), expires=datetime.utcnow() + timedelta(hours=1)).where(Sessions.session == jwt["jti"]).execute()
            set_access_cookies(response, access_token)
            info(f"Refreshed JWT for {get_jwt_identity()}")
        return response
    except (RuntimeError, KeyError):
        return response


def check_if_token_revoked(jwt_header, jwt_payload: dict) -> bool:
    jti = jwt_payload["jti"]
    token = Sessions.get_or_none(Sessions.session == jti)

    return token is None

def user_identity_lookup(user):
    return user

def user_lookup_callback(_jwt_header, jwt_data):
    identity = jwt_data["sub"]
    user = Accounts.get_by_id(identity)
    return model_to_dict(user, recurse=True, backrefs=True, exclude=[Accounts.password])

def login_required_unless_setup():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if not server_verified(): return fn(*args, **kwargs)
            if getenv("DISABLE_BUILTIN_AUTH", "false") == "false":
                try:
                    verify_jwt_in_request()
                except Exception as e:
                    from app import htmx
                    if htmx:
                        response = make_response(render_template("login.html"))
                        response.headers["HX-Redirect"] = "/login" + "?toast=" + "You need to be logged in to access that page"
                        response.headers["HX-Push"] = "/login"
                        return response
                    else:
                        return redirect("/login")

            return fn(*args, **kwargs)

        return decorator

    return wrapper

def login_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if not server_verified(): return redirect("/setup")
            if getenv("DISABLE_BUILTIN_AUTH", "false") == "false":
                try:
                    verify_jwt_in_request()
                except Exception as e:
                    from app import htmx
                    if htmx:
                        response = make_response(render_template("login.html"))
                        response.headers["HX-Redirect"] = "/login" + "?toast=" + "You need to be logged in to access that page"
                        response.headers["HX-Push"] = "/login"
                        return response
                    else:
                        return redirect("/login")

            return fn(*args, **kwargs)

        return decorator

    return wrapper

def logged_out_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if not server_verified(): return redirect("/setup")
            if getenv("DISABLE_BUILTIN_AUTH", "false") == "true":
                return fn(*args, **kwargs)

            try:
                verify_jwt_in_request()
            except Exception as e:
                return fn(*args, **kwargs)

            from app import htmx
            if htmx:
                response = make_response(render_template("admin.html", subpath="admin/invite.html"))
                response.headers["HX-Redirect"] = "/admin" + "?toast=" + "You are already logged in"
                response.headers["HX-Push"] = "/admin"
                return response
            else:
                return redirect("/admin" + "?toast=" + "You are already logged in")

        return decorator

    return wrapper

def server_verified_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if not server_verified(): return redirect("/setup")
            return fn(*args, **kwargs)

        return decorator

    return wrapper

def server_not_verified_required():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if server_verified(): return redirect("/admin")
            return fn(*args, **kwargs)

        return decorator

    return wrapper