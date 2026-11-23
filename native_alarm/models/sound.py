import base64
import binascii
import hashlib
from pathlib import PurePath
from urllib.parse import quote

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from .instrumentation import logged_operation


class AlarmSound(models.Model):
    _name = 'native.alarm.sound'
    _description = 'Alarm Sound Library'
    _check_company_auto = True

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company,
        help='Leave empty to share this approved sound across companies.')
    filename = fields.Char(required=True)
    data = fields.Binary(string='Audio file', attachment=True, required=True)
    checksum = fields.Char(compute='_compute_audio_metadata', store=True)
    mimetype = fields.Char(compute='_compute_audio_metadata', store=True)
    preview_url = fields.Char(compute='_compute_preview_url')

    def _audio_bytes(self):
        self.ensure_one()
        limit = (self.company_id or self.env.company).alarm_sound_max_mb * 1024 * 1024
        encoded = self.with_context(bin_size=False).data or b''
        if len(encoded) > (limit + 2) // 3 * 4:
            raise ValidationError(_('The audio file exceeds the configured upload limit.'))
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValidationError(_('Upload a valid audio file.')) from None
        if not raw or len(raw) > limit:
            raise ValidationError(_('The audio file is empty or exceeds the configured upload limit.'))
        return raw

    def _detect_audio(self, raw):
        """Container signatures are technical format invariants, not business settings."""
        self.ensure_one()
        suffix = PurePath(self.filename or '').suffix.lower()
        formats = {
            '.mp3': ('audio/mpeg', raw.startswith(b'ID3') or (len(raw) > 1 and raw[0] == 255 and raw[1] & 224 == 224)),
            '.wav': ('audio/wav', raw[:4] == b'RIFF' and raw[8:12] == b'WAVE'),
            '.ogg': ('audio/ogg', raw.startswith(b'OggS')),
            '.oga': ('audio/ogg', raw.startswith(b'OggS')),
            '.flac': ('audio/flac', raw.startswith(b'fLaC')),
            '.m4a': ('audio/mp4', len(raw) >= 12 and raw[4:8] == b'ftyp'),
            '.aac': ('audio/aac', len(raw) > 1 and raw[0] == 255 and raw[1] & 246 == 240),
            '.wma': ('audio/x-ms-wma', raw.startswith(bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c'))),
        }
        mimetype, valid = formats.get(suffix, (False, False))
        if not valid:
            raise ValidationError(_('Upload an MP3, WAV, OGG/OGA, FLAC, M4A, AAC, or WMA audio file with matching contents.'))
        return mimetype

    @api.depends('data', 'filename', 'company_id')
    def _compute_audio_metadata(self):
        for sound in self:
            if not sound.data:
                sound.mimetype = False
                sound.checksum = False
                continue
            raw = sound._audio_bytes()
            sound.mimetype = sound._detect_audio(raw)
            sound.checksum = hashlib.sha256(raw).hexdigest()

    @api.depends('checksum')
    def _compute_preview_url(self):
        for sound in self:
            sound.preview_url = (f'/web/content/native.alarm.sound/{sound.id}/data/{quote(sound.filename or "", safe="")}'
                                 f'?unique={sound.checksum}') if sound.id and sound.checksum else False

    @api.constrains('data', 'filename', 'company_id')
    def _check_audio(self):
        for sound in self:
            if '/' in sound.filename or '\\' in sound.filename or any(ord(c) < 32 for c in sound.filename):
                raise ValidationError(_('Use a plain audio filename without folders or control characters.'))
            sound._detect_audio(sound._audio_bytes())

    def _descriptor(self):
        self.ensure_one()
        return {'id': self.id, 'checksum': self.checksum, 'filename': self.filename,
                'mimetype': self.mimetype, 'url': self.preview_url}

    @api.model_create_multi
    @logged_operation('UPLOAD_SOUND')
    def create(self, vals_list):
        return super().create(vals_list)

    @logged_operation('UPDATE_SOUND')
    def write(self, vals):
        if 'company_id' in vals and any(s.company_id.id != vals['company_id'] for s in self):
            raise ValidationError(_('Archive and upload a new sound to change its company scope.'))
        return super().write(vals)

    @logged_operation('DELETE_SOUND')
    def unlink(self):
        return super().unlink()
