import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.template.defaultfilters import filesizeformat
from PIL import Image

# Each rule is shown as a checklist item on the "Set your password" screen.
# static/js/auth.js mirrors these checks for live feedback; keep both in sync.
PASSWORD_RULES = [
    ("length", "At least 12 characters", lambda p: len(p) >= 12),
    ("upper", "At least one uppercase letter", lambda p: re.search(r"[A-Z]", p)),
    ("lower", "At least one lowercase letter", lambda p: re.search(r"[a-z]", p)),
    ("number_or_symbol", "At least one number or symbol", lambda p: re.search(r"[^A-Za-z]", p)),
]

PASSWORD_RULE_ERROR_CODE = "password_rule"


class PhogbsPasswordValidator:
    def validate(self, password, user=None):
        failed = [label for _, label, check in PASSWORD_RULES if not check(password)]
        if failed:
            raise ValidationError(
                [ValidationError(label, code=PASSWORD_RULE_ERROR_CODE) for label in failed]
            )

    def get_help_text(self):
        return "Your password must contain " + ", ".join(
            label[0].lower() + label[1:] for _, label, _ in PASSWORD_RULES
        ) + "."


IDENTITY_DOCUMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".pdf"}
IDENTITY_DOCUMENT_ACCEPT = ".png,.jpg,.jpeg,.gif,.pdf"
_IMAGE_FORMATS = {"PNG", "JPEG", "GIF"}


def validate_identity_document(upload):
    """Check size, extension and actual file content of an identity document.

    SVG is deliberately not accepted: it can carry script and is not a
    sensible format for a scanned identity document.
    """
    max_bytes = settings.IDENTITY_DOCUMENT_MAX_BYTES
    if upload.size > max_bytes:
        raise ValidationError(
            f"The file is too large. The maximum size is {filesizeformat(max_bytes)}.",
            code="file_too_large",
        )

    name = (upload.name or "").lower()
    extension = name[name.rfind(".") :] if "." in name else ""
    if extension not in IDENTITY_DOCUMENT_EXTENSIONS:
        raise ValidationError("Upload a PNG, JPG, GIF or PDF file.", code="file_type")

    upload.seek(0)
    if extension == ".pdf":
        is_valid = upload.read(5) == b"%PDF-"
    else:
        try:
            with Image.open(upload) as image:
                image.verify()
                is_valid = image.format in _IMAGE_FORMATS
        except Exception:
            is_valid = False
    upload.seek(0)

    if not is_valid:
        raise ValidationError(
            "This file is damaged or isn't the type its name suggests.", code="file_content"
        )


def validate_identity_number(value):
    if not re.fullmatch(r"\d{11}", value or ""):
        raise ValidationError("Enter all 11 digits.", code="identity_number")


def validate_phone(value):
    digits = re.sub(r"\D", "", value)
    if not re.fullmatch(r"\+?[\d\s\-()]+", value) or not 7 <= len(digits) <= 15:
        raise ValidationError("Enter a valid phone number.", code="phone")
