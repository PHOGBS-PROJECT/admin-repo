"""Load test for the management platform (https://locust.io).

    pip install -r requirements-dev.txt
    locust -f loadtests/locustfile.py --host https://staging.example.com

Then open http://localhost:8089, choose the number of users and spawn rate.

Signed-in scenarios need real accounts on the target site. Create them on a
staging copy (never production) and pass them in, e.g.:

    LOADTEST_ADMIN_EMAIL=admin@example.com LOADTEST_ADMIN_PASSWORD=... locust -f ...

Watch the response-time percentiles and failure rate, and the database's CPU
and connection count while it runs; those show where the limits are.
"""

import os
import re
import random

from locust import HttpUser, between, task

CSRF_RE = re.compile(r'name="csrfmiddlewaretoken" value="([^"]+)"')
SEARCH_TERMS = ["john", "admin", "phogbs", "finance", "exam", "nigerian", "zz-none"]


def _csrf(response):
    match = CSRF_RE.search(response.text)
    return match.group(1) if match else ""


class Visitor(HttpUser):
    """Someone who isn't signed in: the sign-in and password reset pages."""

    weight = 1
    wait_time = between(2, 6)

    @task(3)
    def sign_in_page(self):
        self.client.get("/auth/login/", name="/auth/login/")

    @task(1)
    def forgot_password_page(self):
        self.client.get("/auth/forgot-password/", name="/auth/forgot-password/")


class Administrator(HttpUser):
    """A school administrator using the Overview and Staff Directory."""

    weight = 3
    wait_time = between(1, 4)

    def on_start(self):
        email = os.environ.get("LOADTEST_ADMIN_EMAIL")
        password = os.environ.get("LOADTEST_ADMIN_PASSWORD")
        if not email or not password:
            raise RuntimeError("Set LOADTEST_ADMIN_EMAIL and LOADTEST_ADMIN_PASSWORD.")
        page = self.client.get("/auth/login/", name="/auth/login/")
        response = self.client.post(
            "/auth/login/",
            {"email": email, "password": password, "csrfmiddlewaretoken": _csrf(page)},
            headers={"Referer": self.host + "/auth/login/"},
            name="/auth/login/ [submit]",
        )
        if "/auth/login/" in response.url:
            raise RuntimeError("Sign-in failed; check the load-test account.")

    @task(4)
    def overview(self):
        self.client.get("/", name="/ (overview)")

    @task(3)
    def staff_directory(self):
        self.client.get("/people/staff/", name="/people/staff/")

    @task(3)
    def staff_search(self):
        term = random.choice(SEARCH_TERMS)
        self.client.get(f"/people/staff/all/?q={term}", name="/people/staff/all/?q=…")

    @task(2)
    def staff_filtered_page(self):
        self.client.get("/people/staff/all/?status=active&page=2", name="/people/staff/all/?status&page")

    @task(2)
    def invitations(self):
        self.client.get("/people/invitations/?status=pending", name="/people/invitations/")

    @task(1)
    def roles(self):
        self.client.get("/people/roles/?role=faculty", name="/people/roles/")

    @task(1)
    def api_me(self):
        self.client.get("/api/v1/me/", name="/api/v1/me/")
