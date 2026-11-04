from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.accounts.identity import IdentityRecord
from apps.accounts.models import User

from .helpers import PrivateMediaMixin, make_user, png_upload

PROFILE_URL = reverse("accounts:setup_profile")
IDENTITY_URL = reverse("accounts:setup_identity")
DOCUMENT_API = reverse("accounts_api:identity_document")
LOOKUP_API = reverse("accounts_api:identity_lookup")


class SetupFlowTests(PrivateMediaMixin, TestCase):
    def setUp(self):
        self.user = make_user(email="chisom@example.com", onboarded=False)
        self.client.force_login(self.user)

    def test_dashboard_redirects_to_setup(self):
        self.assertRedirects(self.client.get(reverse("dashboard:home")), PROFILE_URL)

    def test_profile_step(self):
        response = self.client.get(PROFILE_URL)
        self.assertContains(response, "Let's get to know you")
        self.assertContains(response, 'value="chisom@example.com" readonly')

        response = self.client.post(
            PROFILE_URL, {"first_name": " Chisom ", "last_name": "Kelechi", "phone": "+234 803 123 4567"}
        )
        self.assertRedirects(response, IDENTITY_URL)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Chisom")

    def test_profile_requires_names_and_valid_phone(self):
        response = self.client.post(PROFILE_URL, {"first_name": "", "last_name": "", "phone": "abc"})
        self.assertContains(response, "Enter your first name")
        self.assertContains(response, "Enter your last name")
        self.assertContains(response, "Enter a valid phone number.")

    def test_identity_step_requires_profile_first(self):
        self.assertRedirects(self.client.get(IDENTITY_URL), PROFILE_URL)

    def complete_profile(self):
        User.objects.filter(pk=self.user.pk).update(first_name="Chisom", last_name="Kelechi")

    def test_identity_step_with_form_upload(self):
        self.complete_profile()
        response = self.client.post(
            IDENTITY_URL,
            {"identity_method": "nin", "identity_number": "12345678901", "identity_document": png_upload()},
        )
        self.assertRedirects(response, reverse("accounts:setup_complete"))
        self.user.refresh_from_db()
        self.assertFalse(self.user.needs_onboarding)
        self.assertEqual(self.user.identity_method, "nin")
        self.assertEqual(self.user.identity_document_name, "id-card.png")
        self.assertTrue(self.user.identity_document.storage.exists(self.user.identity_document.name))

        response = self.client.get(reverse("accounts:setup_complete"))
        self.assertContains(response, "You are all set!")
        self.assertEqual(self.client.get(reverse("dashboard:home")).status_code, 200)

    def test_identity_step_with_document_uploaded_through_api(self):
        self.complete_profile()
        response = self.client.post(DOCUMENT_API, {"document": png_upload()})
        self.assertEqual(response.status_code, 201)
        response = self.client.post(
            IDENTITY_URL, {"identity_method": "bvn", "identity_number": "11335603291"}
        )
        self.assertRedirects(response, reverse("accounts:setup_complete"))

    def test_identity_step_validation(self):
        self.complete_profile()
        response = self.client.post(IDENTITY_URL, {"identity_method": "nin", "identity_number": "123"})
        self.assertContains(response, "Enter all 11 digits.")
        self.assertContains(response, "Upload your identity document")
        self.assertTrue(User.objects.get(pk=self.user.pk).needs_onboarding)

    def test_verified_name_is_stored(self):
        self.complete_profile()
        with mock.patch(
            "apps.accounts.identity.NullIdentityVerifier.lookup",
            return_value=IdentityRecord("Chisom Chukwu Kelechi"),
        ):
            self.client.post(
                IDENTITY_URL,
                {"identity_method": "bvn", "identity_number": "11335603291", "identity_document": png_upload()},
            )
        self.user.refresh_from_db()
        self.assertEqual(self.user.identity_verified_name, "Chisom Chukwu Kelechi")

    def test_setup_is_closed_once_complete(self):
        self.user.first_name, self.user.last_name = "Chisom", "Kelechi"
        self.user.profile_completed_at = "2026-11-04T10:00:00Z"
        self.user.save()
        self.assertRedirects(self.client.get(PROFILE_URL), reverse("dashboard:home"))
        self.assertEqual(self.client.post(DOCUMENT_API, {"document": png_upload()}).status_code, 403)


class IdentityDocumentApiTests(PrivateMediaMixin, TestCase):
    def setUp(self):
        self.user = make_user(email="chisom@example.com", onboarded=False)
        self.client.force_login(self.user)

    def test_upload_and_clear(self):
        response = self.client.post(DOCUMENT_API, {"document": png_upload()})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["name"], "id-card.png")
        self.user.refresh_from_db()
        stored_name = self.user.identity_document.name
        storage = self.user.identity_document.storage
        self.assertTrue(storage.exists(stored_name))
        self.assertNotIn("id-card", stored_name)

        response = self.client.delete(DOCUMENT_API)
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertFalse(self.user.identity_document)
        self.assertFalse(storage.exists(stored_name))

    def test_replacing_deletes_old_file(self):
        self.client.post(DOCUMENT_API, {"document": png_upload()})
        self.user.refresh_from_db()
        first = self.user.identity_document.name
        self.client.post(DOCUMENT_API, {"document": png_upload("second.png")})
        self.assertFalse(self.user.identity_document.storage.exists(first))

    def test_pdf_is_accepted(self):
        pdf = SimpleUploadedFile("id.pdf", b"%PDF-1.4\n%fake", content_type="application/pdf")
        self.assertEqual(self.client.post(DOCUMENT_API, {"document": pdf}).status_code, 201)

    def test_rejects_wrong_type(self):
        svg = SimpleUploadedFile("id.svg", b"<svg onload='alert(1)'/>", content_type="image/svg+xml")
        response = self.client.post(DOCUMENT_API, {"document": svg})
        self.assertEqual(response.status_code, 400)
        self.assertIn("PNG, JPG, GIF or PDF", response.json()["document"][0])

    def test_rejects_disguised_file(self):
        fake = SimpleUploadedFile("id.png", b"not really a png", content_type="image/png")
        response = self.client.post(DOCUMENT_API, {"document": fake})
        self.assertEqual(response.status_code, 400)

    def test_rejects_large_file(self):
        with self.settings(IDENTITY_DOCUMENT_MAX_BYTES=10):
            response = self.client.post(DOCUMENT_API, {"document": png_upload()})
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", response.json()["document"][0])

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.post(DOCUMENT_API, {"document": png_upload()}).status_code, 403)


class IdentityLookupApiTests(TestCase):
    def setUp(self):
        self.client.force_login(make_user(onboarded=False))

    def test_no_provider_returns_no_name(self):
        response = self.client.post(LOOKUP_API, {"method": "bvn", "number": "11335603291"})
        self.assertEqual(response.json(), {"name": None})

    def test_returns_provider_name(self):
        with mock.patch(
            "apps.accounts.identity.NullIdentityVerifier.lookup",
            return_value=IdentityRecord("Chisom Chukwu Kelechi"),
        ):
            response = self.client.post(LOOKUP_API, {"method": "bvn", "number": "11335603291"})
        self.assertEqual(response.json(), {"name": "Chisom Chukwu Kelechi"})

    def test_validates_number(self):
        response = self.client.post(LOOKUP_API, {"method": "nin", "number": "12ab"})
        self.assertEqual(response.status_code, 400)
