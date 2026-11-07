"""Tests for the scalability changes: indexed email lookups, the email queue,
permission caching, direct-to-bucket uploads and the read-replica router."""

import smtplib
from unittest import mock

from django.core import mail
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, RolePermission, User, private_storage
from apps.accounts.permissions import role_levels
from apps.accounts.tasks import _build, _serialise, queue_email
from apps.accounts.uploads import confirm_identity_upload
from config import db_router

from .helpers import STRONG_PASSWORD, PrivateMediaMixin, make_user, png_upload


class EmailLookupTests(TestCase):
    def test_login_lookup_is_exact_and_case_insensitive(self):
        user = make_user(email="lilian@example.com")
        self.assertEqual(User.objects.get_by_natural_key("  LILIAN@Example.COM "), user)

    def test_login_query_uses_exact_match(self):
        make_user(email="lilian@example.com")
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            User.objects.get_by_natural_key("Lilian@Example.com")
        sql = queries.captured_queries[0]["sql"].lower()
        self.assertNotIn("like", sql)
        self.assertNotIn("upper", sql)

    def test_password_reset_matches_any_case(self):
        make_user(email="lilian@example.com")
        self.client.post(reverse("accounts:password_reset"), {"email": "LILIAN@example.com"})
        self.assertEqual(len(mail.outbox), 1)


class EmailQueueTests(TestCase):
    def test_message_round_trips_through_the_task_payload(self):
        message = EmailMultiAlternatives("Hi", "Body", "from@phogbs.com", ["a@example.com"],
                                         cc=["c@example.com"], reply_to=["r@example.com"])
        message.attach_alternative("<p>Body</p>", "text/html")
        rebuilt = _build(_serialise(message))
        self.assertEqual(rebuilt.to, ["a@example.com"])
        self.assertEqual(rebuilt.cc, ["c@example.com"])
        self.assertEqual(rebuilt.alternatives[0][0], "<p>Body</p>")

    def test_without_a_broker_mail_is_sent_inline(self):
        queue_email(EmailMultiAlternatives("Hi", "Body", None, ["a@example.com"]))
        self.assertEqual(len(mail.outbox), 1)

    def test_inline_failures_reach_the_caller(self):
        with mock.patch.object(EmailMultiAlternatives, "send", side_effect=smtplib.SMTPException):
            with self.assertRaises(smtplib.SMTPException):
                queue_email(EmailMultiAlternatives("Hi", "Body", None, ["a@example.com"]))


class PermissionCacheTests(TestCase):
    def test_overrides_clear_the_cached_levels(self):
        self.assertEqual(role_levels(Role.FINANCE_ADMIN)["staff_all"], "none")  # now cached
        row = RolePermission.objects.create(role=Role.FINANCE_ADMIN, module="staff_all", level="view")
        self.assertEqual(role_levels(Role.FINANCE_ADMIN)["staff_all"], "view")
        row.delete()
        self.assertEqual(role_levels(Role.FINANCE_ADMIN)["staff_all"], "none")

    @override_settings(CACHES={"default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "permission-cache-test",
    }})
    def test_cached_levels_avoid_queries(self):
        # With a memory cache (Redis in production) a cached lookup needs no
        # queries; the database cache used in dev is itself one query.
        from django.core.cache import cache

        cache.clear()
        role_levels(Role.EXAM_OFFICER)
        with self.assertNumQueries(0):
            role_levels(Role.EXAM_OFFICER)


class DirectUploadTests(PrivateMediaMixin, TestCase):
    def setUp(self):
        self.user = make_user(email="chisom@example.com", onboarded=False)
        self.client.force_login(self.user)

    def store(self, key, content):
        return private_storage().save(key, ContentFile(content))

    def test_endpoints_hidden_without_a_bucket(self):
        response = self.client.post(reverse("accounts_api:identity_upload_url"),
                                    {"name": "id.png", "size": 10}, content_type="application/json")
        self.assertEqual(response.status_code, 404)

    @override_settings(PRIVATE_FILES_SIGNED_URLS=True)
    def test_presign_validates_and_returns_a_url(self):
        with mock.patch("apps.accounts.uploads.private_storage") as storage:
            storage.return_value.bucket_name = "private"
            storage.return_value.connection.meta.client.generate_presigned_url.return_value = "https://s3/put"
            response = self.client.post(reverse("accounts_api:identity_upload_url"),
                                        {"name": "id.PNG", "size": 1000},
                                        content_type="application/json")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["url"], "https://s3/put")
        self.assertTrue(body["key"].startswith(f"identity-documents/{self.user.pk}/"))
        self.assertEqual(body["headers"], {"Content-Type": "image/png"})

        response = self.client.post(reverse("accounts_api:identity_upload_url"),
                                    {"name": "id.svg", "size": 1000}, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        response = self.client.post(reverse("accounts_api:identity_upload_url"),
                                    {"name": "id.png", "size": 10 * 1024 * 1024},
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @override_settings(PRIVATE_FILES_SIGNED_URLS=True)
    def test_confirm_attaches_a_valid_upload(self):
        key = self.store(f"identity-documents/{self.user.pk}/abc.png", png_upload().read())
        response = self.client.post(reverse("accounts_api:identity_upload_confirm"),
                                    {"key": key, "name": "my-id.png"}, content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.user.refresh_from_db()
        self.assertEqual(self.user.identity_document.name, key)
        self.assertEqual(self.user.identity_document_name, "my-id.png")

    def test_confirm_rejects_other_users_and_bad_files(self):
        other_key = self.store("identity-documents/999/abc.png", png_upload().read())
        with self.assertRaisesMessage(Exception, "doesn't belong"):
            confirm_identity_upload(self.user, other_key, "x.png")

        bad_key = self.store(f"identity-documents/{self.user.pk}/fake.png", b"not an image")
        with self.assertRaisesMessage(Exception, "damaged"):
            confirm_identity_upload(self.user, bad_key, "fake.png")
        self.assertFalse(private_storage().exists(bad_key))

    @override_settings(PRIVATE_FILES_SIGNED_URLS=True)
    def test_document_viewer_redirects_to_a_signed_link(self):
        admin = make_user(email="admin@phogbs.com", role=Role.SCHOOL_ADMIN, is_superuser=True)
        self.user.identity_document.save("id.png", png_upload())
        self.client.force_login(admin)
        with mock.patch("apps.people.views.document_url", return_value="https://s3/signed"):
            response = self.client.get(reverse("people:document", args=[self.user.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://s3/signed")


class ReplicaRouterTests(TestCase):
    def setUp(self):
        self.router = db_router.PrimaryReplicaRouter()
        self.seen = []

        def view(request):
            self.seen.append(self.router.db_for_read(User))
            return HttpResponse()

        self.middleware = db_router.PrimaryAfterWriteMiddleware(view)

    def test_reads_use_replica_and_writes_primary(self):
        self.middleware(RequestFactory().get("/"))
        response = self.middleware(RequestFactory().post("/"))
        self.assertEqual(self.seen, ["replica", "default"])
        self.assertEqual(self.router.db_for_write(User), "default")
        self.assertIn(db_router.PIN_COOKIE, response.cookies)

    def test_reads_stay_on_primary_just_after_a_write(self):
        request = RequestFactory().get("/")
        request.COOKIES[db_router.PIN_COOKIE] = "1"
        self.middleware(request)
        self.assertEqual(self.seen, ["default"])

    def test_migrations_only_on_primary(self):
        self.assertTrue(self.router.allow_migrate("default", "accounts"))
        self.assertFalse(self.router.allow_migrate("replica", "accounts"))
