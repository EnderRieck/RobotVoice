# coding: utf-8

try:
    text_type = unicode
    binary_type = str
    string_types = (basestring,)
    PY2 = True
except NameError:
    text_type = str
    binary_type = bytes
    string_types = (str,)
    PY2 = False


def to_text(value, default=u""):
    if value is None:
        return default
    if isinstance(value, text_type):
        return value
    if isinstance(value, binary_type):
        try:
            return value.decode("utf-8")
        except Exception:
            return value.decode("utf-8", "ignore")
    try:
        return text_type(value)
    except Exception:
        try:
            return text_type(repr(value))
        except Exception:
            return default


def to_ros_string(value):
    if value is None:
        return ""
    if PY2:
        if isinstance(value, text_type):
            return value.encode("utf-8")
        if isinstance(value, binary_type):
            return value
        return to_text(value).encode("utf-8")
    return to_text(value)


def to_utf8_bytes(value):
    if value is None:
        return b""
    if isinstance(value, binary_type):
        return value
    return to_text(value).encode("utf-8")
