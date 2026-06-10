import base64
import binascii
import io
import logging

from PIL import ImageChops

from odoo.exceptions import ValidationError
from odoo.tools.image import Image
from odoo.tools.mimetypes import guess_mimetype

_logger = logging.getLogger(__name__)


def validate_png_payload(payload, *, filename=None, label='image'):
    if not payload:
        return 0

    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, TypeError) as error:
        _logger.warning(
            "Rejected %s upload filename=%s: invalid base64 payload",
            label,
            filename or '<none>',
        )
        raise ValidationError("The uploaded image could not be read. Please upload a valid PNG file.") from error

    mimetype = guess_mimetype(raw, default='application/octet-stream')
    if mimetype != 'image/png':
        _logger.warning(
            "Rejected %s upload filename=%s: detected mimetype=%s, size=%s bytes",
            label,
            filename or '<none>',
            mimetype,
            len(raw),
        )
        raise ValidationError("The uploaded image must be a PNG file.") from None

    _logger.debug(
        "Validated %s PNG upload filename=%s size=%s bytes",
        label,
        filename or '<none>',
        len(raw),
    )
    return len(raw)


def tint_png_payload(payload, *, rgb=(17, 58, 140), label='image'):
    if not payload:
        return False

    try:
        raw = base64.b64decode(payload)
        image = Image.open(io.BytesIO(raw)).convert('RGBA')
    except Exception:
        _logger.exception("Could not tint %s PNG payload", label)
        return payload

    red, green, blue = rgb
    tinted = Image.new('RGBA', image.size, (red, green, blue, 0))
    alpha = image.getchannel('A')
    luminance = image.convert('L')
    ink_alpha = Image.eval(luminance, lambda pixel: 255 - pixel)
    tinted.putalpha(ImageChops.multiply(alpha, ink_alpha))

    output = io.BytesIO()
    tinted.save(output, format='PNG')
    result = base64.b64encode(output.getvalue())
    _logger.debug(
        "Tinted %s PNG payload original_size=%s tinted_size=%s",
        label,
        len(raw),
        len(result),
    )
    return result
