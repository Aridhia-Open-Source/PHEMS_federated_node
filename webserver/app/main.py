"""
A collection of general use endpoints
These won't have any restrictions and won't go through
    Keycloak for token validation.
"""
from http import HTTPStatus
import requests
from flask import Blueprint, redirect, url_for, request
from app.helpers.keycloak import Keycloak, URLS

bp = Blueprint('main', __name__, url_prefix='/')

@bp.route('/')
def index():
    """
    GET / endpoint.
        Redirects to /health_check
    """
    return redirect(url_for('main.health_check'))

@bp.route("/ready_check")
def ready_check():
    """
    GET /ready_check endpoint
        Mostly to tell k8s Flask has started
    """
    return {"status": "ready"}, HTTPStatus.OK

@bp.route("/health_check")
def health_check():
    """
    GET /health_check endpoint
        Checks the connection to keycloak and returns a jsonized summary
    """
    try:
        kc_request = requests.get(URLS["health_check"], timeout=30)
        kc_status = kc_request.ok
        status_text = "ok" if kc_request.ok else "non operational"
        code = HTTPStatus.OK if kc_request.ok else HTTPStatus.BAD_GATEWAY
    except requests.exceptions.ConnectionError:
        kc_status = False
        status_text = "non operational"
        code = HTTPStatus.BAD_GATEWAY

    return {
        "status": status_text,
        "keycloak": kc_status
    }, code

@bp.route("/login", methods=['POST'])
def login():
    """
    POST /login endpoint.
        Given a form, logs the user in, returning a refresh_token from Keycloak
    """
    credentials = request.form.to_dict()
    return {
        "token": Keycloak().get_token(**credentials)
    }, HTTPStatus.OK
