import base64
import io
import wave

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from .common import AlarmCase


def wave_data():
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\0\0' * 80)
    return base64.b64encode(output.getvalue())


@tagged('post_install', '-at_install')
class TestAlarmSound(AlarmCase):
    def sound(self, **values):
        vals = {'name': 'Approved song', 'filename': 'alarm.wav', 'data': wave_data()}
        vals.update(values)
        return self.env['native.alarm.sound'].create(vals)

    def test_sound_default_and_specific_override(self):
        default = self.sound()
        custom = self.sound(name='Specific alarm')
        self.env.company.alarm_sound_id = default
        alarm = self.alarm()
        self.assertEqual(alarm._payload()['sound']['id'], default.id)
        alarm.sound_id = custom
        self.assertEqual(alarm._payload()['sound']['id'], custom.id)
        alarm.sound_id = False
        self.assertEqual(alarm._payload()['sound']['id'], default.id)
        self.env.company.alarm_sound_id = False
        self.assertFalse(alarm._payload()['sound'])

    def test_sound_upload_permissions_and_company_boundary(self):
        sound = self.sound()
        self.assertTrue(sound.with_user(self.owner).read(['data'])[0]['data'])
        with self.assertRaises(AccessError):
            self.env['native.alarm.sound'].with_user(self.owner).create({
                'name': 'Not authorised', 'filename': 'alarm.wav', 'data': wave_data()})
        company = self.env['res.company'].create({'name': 'Sound company B'})
        private = self.sound(company_id=company.id)
        with self.assertRaises(AccessError):
            private.with_user(self.owner).read(['data'])

    def test_sound_rejects_mismatched_content_and_limit(self):
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.sound(filename='fake.mp3', data=base64.b64encode(b'<script>not audio</script>'))
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.sound(filename='../alarm.wav')
        self.env.company.alarm_sound_max_mb = 1
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.sound(data=base64.b64encode(b'RIFF' + b'\0' * (1024 * 1024)))

    def test_sound_metadata_and_private_preview(self):
        sound = self.sound(filename='my song.wav')
        self.assertEqual(sound.mimetype, 'audio/wav')
        self.assertEqual(len(sound.checksum), 64)
        self.assertIn('my%20song.wav', sound.preview_url)
        self.assertNotIn('access_token', sound.preview_url)
        old = sound.checksum
        sound.write({'data': base64.b64encode(base64.b64decode(wave_data()) + b'\0')})
        self.assertNotEqual(sound.checksum, old)

    def test_common_audio_container_signatures(self):
        fixtures = {
            'song.mp3': b'ID3\x04\0\0\0\0\0\0',
            'song.ogg': b'OggS' + b'\0' * 32,
            'song.flac': b'fLaC' + b'\0' * 32,
            'song.m4a': b'\0\0\0\x18ftypM4A ' + b'\0' * 16,
            'song.aac': b'\xff\xf1' + b'\0' * 16,
            'song.wma': bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c') + b'\0' * 16,
        }
        for filename, raw in fixtures.items():
            with self.subTest(filename=filename):
                self.assertTrue(self.sound(filename=filename, data=base64.b64encode(raw)).mimetype.startswith('audio/'))

    def test_company_default_cannot_reference_another_private_company_sound(self):
        company = self.env['res.company'].create({'name': 'Private sounds'})
        sound = self.sound(company_id=company.id)
        with self.assertRaises(ValidationError), self.cr.savepoint():
            self.env.company.alarm_sound_id = sound
        shared = self.sound(company_id=False)
        self.env.company.alarm_sound_id = shared
        self.assertEqual(self.env.company.alarm_sound_id, shared)
