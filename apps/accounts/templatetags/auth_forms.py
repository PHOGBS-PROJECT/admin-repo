from django import template

register = template.Library()


@register.simple_tag
def widget(field, **attrs):
    """Render a field's widget, pointing aria-describedby at its error text."""
    if field.errors:
        attrs.setdefault("aria-describedby", f"{field.auto_id}_error")
    return field.as_widget(attrs=attrs)
