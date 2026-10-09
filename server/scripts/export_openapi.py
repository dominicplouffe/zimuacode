"""Prints the OpenAPI schema; the web app generates its API types from it."""

import json

from app.main import create_app

print(json.dumps(create_app().openapi(), indent=2))
