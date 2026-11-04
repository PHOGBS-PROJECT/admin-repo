from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.accounts.validators import PhogbsPasswordValidator


class PasswordValidatorTests(SimpleTestCase):
    validator = PhogbsPasswordValidator()

    def failures(self, password):
        try:
            self.validator.validate(password)
        except ValidationError as error:
            return [e.message for e in error.error_list]
        return []

    def test_strong_password_passes(self):
        self.assertEqual(self.failures("Pipeline-Econ-2026"), [])

    def test_design_example_fails_upper_only(self):
        # "lilian11111111" from the design: long enough, has digits, no uppercase.
        self.assertEqual(self.failures("lilian11111111"), ["At least one uppercase letter"])

    def test_each_rule(self):
        self.assertIn("At least 12 characters", self.failures("Short-1"))
        self.assertIn("At least one lowercase letter", self.failures("ALLUPPERCASE-1"))
        self.assertIn("At least one number or symbol", self.failures("OnlyLettersHere"))
