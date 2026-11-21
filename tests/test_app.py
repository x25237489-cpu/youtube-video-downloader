import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

class URLSafetyTests(unittest.TestCase):
    def test_valid_url_forms(self):
        for url in [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ?t=1',
            'https://www.youtube.com/shorts/dQw4w9WgXcQ',
            'https://youtube.com/live/dQw4w9WgXcQ',
        ]:
            with self.subTest(url=url):
                self.assertEqual(app.validate_youtube_url(url), ('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 'dQw4w9WgXcQ'))

    def test_rejects_untrusted_urls(self):
        bad = [
            'http://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtube.com.evil.net/watch?v=dQw4w9WgXcQ',
            'https://youtube.com@evil.net/watch?v=dQw4w9WgXcQ',
            'https://youtu.be.bad.org/dQw4w9WgXcQ',
            'https://127.0.0.1/watch?v=dQw4w9WgXcQ',
            'https://www.youtube.com/playlist?list=PL123',
            'https://youtu.be/dQw4w9WgXcQ/extra',
            'https://www.youtube.com/watch?v=bad',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ&v=AAAAAAAAAAA',
            'file:///etc/passwd',
            '',
        ]
        for url in bad:
            with self.subTest(url=url), self.assertRaises(ValueError):
                app.validate_youtube_url(url)

    def test_public_job_hides_internals(self):
        job = {'url':'private','video_id':'xxx','internal_error':'xxx','title':'OK','progress':0}
        self.assertEqual(app.public_job(job), {'title':'OK','progress':0})

    def test_template_is_ytdlp_safe(self):
        fmt = app.format_options('mp4','720',Path('/tmp'),lambda _:None)
        self.assertIn('%(id)s', fmt['outtmpl'])
        self.assertTrue(fmt['noplaylist'])
        self.assertIn('max_filesize', fmt)

if __name__ == '__main__':
    unittest.main()
